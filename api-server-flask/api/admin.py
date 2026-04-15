"""
Flask-Admin setup for WMS tool.
Access at: http://localhost:5000/admin
Login with your email/password (admin role required).
"""

from flask import redirect, url_for, request, session, flash
from flask_admin import Admin, AdminIndexView, expose
from flask_admin.base import BaseView
import pymysql
from wtforms import SelectField, StringField, PasswordField
from wtforms.validators import DataRequired, Email
from flask_admin.form import BaseForm
import wtforms

from .db_manager import mysql_manager


# ──────────────────────────────────────────────
# Session-based admin auth (simple, no extra lib)
# ──────────────────────────────────────────────

def is_admin_logged_in():
    return session.get('admin_logged_in', False)


# ──────────────────────────────────────────────
# Custom Admin Index with login form
# ──────────────────────────────────────────────

class SecureAdminIndexView(AdminIndexView):

    @expose('/')
    def index(self):
        if not is_admin_logged_in():
            return redirect(url_for('admin.login_view'))
        return self.render('admin/index.html')

    @expose('/login', methods=['GET', 'POST'])
    def login_view(self):
        if is_admin_logged_in():
            return redirect(url_for('admin.index'))

        error = None
        if request.method == 'POST':
            email = request.form.get('email', '').strip().lower()
            password = request.form.get('password', '')

            result = mysql_manager.execute_query(
                "SELECT id, username, email, password, role, status FROM users WHERE email = %s",
                (email,)
            )
            if result:
                user = result[0]
                from werkzeug.security import check_password_hash
                if check_password_hash(user['password'], password):
                    if user['role'] == 'admin':
                        session['admin_logged_in'] = True
                        session['admin_email'] = user['email']
                        session['admin_username'] = user['username']
                        return redirect(url_for('admin.index'))
                    else:
                        error = 'You do not have admin access.'
                else:
                    error = 'Invalid email or password.'
            else:
                error = 'Invalid email or password.'

        return self.render('admin/login.html', error=error)

    @expose('/logout')
    def logout_view(self):
        session.pop('admin_logged_in', None)
        session.pop('admin_email', None)
        session.pop('admin_username', None)
        return redirect(url_for('admin.login_view'))


# ──────────────────────────────────────────────
# Base secure view — blocks non-admins
# ──────────────────────────────────────────────

class SecureView(BaseView):
    def is_accessible(self):
        return is_admin_logged_in()

    def inaccessible_callback(self, name, **kwargs):
        return redirect(url_for('admin.login_view'))


# ──────────────────────────────────────────────
# User management view
# ──────────────────────────────────────────────

class UserManagementView(SecureView):

    @expose('/')
    def index(self):
        users = mysql_manager.execute_query(
            "SELECT id, username, email, status, role, date_joined FROM users ORDER BY date_joined DESC"
        )
        roles = mysql_manager.execute_query("SELECT name FROM roles ORDER BY name")
        role_names = [r['name'] for r in roles]
        return self.render('admin/users.html', users=users, roles=role_names)

    @expose('/approve/<int:user_id>', methods=['POST'])
    def approve(self, user_id):
        role = request.form.get('role', 'viewer')
        mysql_manager.execute_query(
            "UPDATE users SET status='active', role=%s WHERE id=%s",
            (role, user_id), fetch=False
        )
        flash(f'User approved with role: {role}', 'success')
        return redirect(url_for('usermanagement.index'))

    @expose('/block/<int:user_id>', methods=['POST'])
    def block(self, user_id):
        mysql_manager.execute_query(
            "UPDATE users SET status='blocked' WHERE id=%s",
            (user_id,), fetch=False
        )
        flash('User blocked.', 'warning')
        return redirect(url_for('usermanagement.index'))

    @expose('/set-role/<int:user_id>', methods=['POST'])
    def set_role(self, user_id):
        role = request.form.get('role', 'viewer')
        mysql_manager.execute_query(
            "UPDATE users SET role=%s WHERE id=%s",
            (role, user_id), fetch=False
        )
        flash(f'Role updated to: {role}', 'success')
        return redirect(url_for('usermanagement.index'))

    @expose('/reset-password/<int:user_id>', methods=['POST'])
    def reset_password(self, user_id):
        new_password = request.form.get('new_password', '').strip()
        if not new_password or len(new_password) < 4:
            flash('Password must be at least 4 characters.', 'danger')
            return redirect(url_for('usermanagement.index'))
        from werkzeug.security import generate_password_hash
        new_hash = generate_password_hash(new_password)
        mysql_manager.execute_query(
            "UPDATE users SET password=%s WHERE id=%s",
            (new_hash, user_id), fetch=False
        )
        flash('Password reset successfully.', 'success')
        return redirect(url_for('usermanagement.index'))

    @expose('/delete/<int:user_id>', methods=['POST'])
    def delete(self, user_id):
        mysql_manager.execute_query(
            "DELETE FROM users WHERE id=%s", (user_id,), fetch=False
        )
        flash('User deleted.', 'danger')
        return redirect(url_for('usermanagement.index'))


# ──────────────────────────────────────────────
# Warehouse-Company access assignment view
# ──────────────────────────────────────────────

class AccessManagementView(SecureView):

    @expose('/')
    def index(self):
        users = mysql_manager.execute_query(
            "SELECT id, username, email, role, status FROM users WHERE status='active' ORDER BY username"
        )
        return self.render('admin/access.html', users=users)

    @expose('/user/<int:user_id>')
    def user_access(self, user_id):
        user = mysql_manager.execute_query(
            "SELECT id, username, email, role FROM users WHERE id=%s", (user_id,)
        )
        if not user:
            flash('User not found.', 'danger')
            return redirect(url_for('accessmanagement.index'))
        user = user[0]

        warehouses = mysql_manager.execute_query("SELECT warehouse_id, name FROM warehouse ORDER BY name")
        companies = mysql_manager.execute_query("SELECT company_id, name FROM company ORDER BY name")
        current_access = mysql_manager.execute_query(
            """SELECT uwc.id, uwc.warehouse_id, uwc.company_id,
                      w.name as warehouse_name, c.name as company_name
               FROM user_warehouse_company uwc
               JOIN warehouse w ON uwc.warehouse_id = w.warehouse_id
               JOIN company c ON uwc.company_id = c.company_id
               WHERE uwc.user_id = %s""",
            (user_id,)
        )
        return self.render('admin/user_access.html',
                           user=user,
                           warehouses=warehouses,
                           companies=companies,
                           current_access=current_access)

    @expose('/user/<int:user_id>/add', methods=['POST'])
    def add_access(self, user_id):
        warehouse_id = request.form.get('warehouse_id')
        company_id = request.form.get('company_id')
        if warehouse_id and company_id:
            try:
                mysql_manager.execute_query(
                    """INSERT IGNORE INTO user_warehouse_company (user_id, warehouse_id, company_id)
                       VALUES (%s, %s, %s)""",
                    (user_id, warehouse_id, company_id), fetch=False
                )
                flash('Access granted.', 'success')
            except Exception as e:
                flash(f'Error: {str(e)}', 'danger')
        return redirect(url_for('accessmanagement.user_access', user_id=user_id))

    @expose('/user/<int:user_id>/remove/<int:access_id>', methods=['POST'])
    def remove_access(self, user_id, access_id):
        mysql_manager.execute_query(
            "DELETE FROM user_warehouse_company WHERE id=%s AND user_id=%s",
            (access_id, user_id), fetch=False
        )
        flash('Access removed.', 'warning')
        return redirect(url_for('accessmanagement.user_access', user_id=user_id))


# ──────────────────────────────────────────────
# Role Management view
# ──────────────────────────────────────────────

class RoleManagementView(SecureView):

    @expose('/')
    def index(self):
        roles = mysql_manager.execute_query(
            "SELECT role_id, name, description, all_warehouses, eway_bill_admin, eway_bill_filling, supply_sheet FROM roles ORDER BY name"
        )
        # Attach permissions to each role
        from .db_manager import ALL_ORDER_STATES, ALL_UPLOAD_TYPES
        for role in roles:
            states = mysql_manager.execute_query(
                "SELECT state_name FROM role_order_states WHERE role_id=%s", (role['role_id'],)
            )
            uploads = mysql_manager.execute_query(
                "SELECT upload_type FROM role_uploads WHERE role_id=%s", (role['role_id'],)
            )
            role['order_states'] = [r['state_name'] for r in states]
            role['uploads'] = [r['upload_type'] for r in uploads]
        return self.render('admin/roles.html', roles=roles,
                           all_order_states=ALL_ORDER_STATES,
                           all_upload_types=ALL_UPLOAD_TYPES)

    @expose('/create', methods=['GET', 'POST'])
    def create(self):
        from .db_manager import ALL_ORDER_STATES, ALL_UPLOAD_TYPES
        if request.method == 'POST':
            name = request.form.get('name', '').strip().lower().replace(' ', '_')
            description = request.form.get('description', '').strip()
            all_warehouses = request.form.get('all_warehouses') == '1'
            eway_bill_admin = request.form.get('eway_bill_admin') == '1'
            eway_bill_filling = request.form.get('eway_bill_filling') == '1'
            supply_sheet = request.form.get('supply_sheet') == '1'
            order_states = request.form.getlist('order_states')
            uploads = request.form.getlist('uploads')

            if not name:
                flash('Role name is required.', 'danger')
                return self.render('admin/role_form.html', role=None,
                                   all_order_states=ALL_ORDER_STATES,
                                   all_upload_types=ALL_UPLOAD_TYPES)

            existing = mysql_manager.execute_query(
                "SELECT role_id FROM roles WHERE name=%s", (name,)
            )
            if existing:
                flash(f'Role "{name}" already exists.', 'danger')
                return self.render('admin/role_form.html', role=None,
                                   all_order_states=ALL_ORDER_STATES,
                                   all_upload_types=ALL_UPLOAD_TYPES)

            with mysql_manager.get_cursor() as cursor:
                cursor.execute(
                    "INSERT INTO roles (name, description, all_warehouses, eway_bill_admin, eway_bill_filling, supply_sheet) VALUES (%s,%s,%s,%s,%s,%s)",
                    (name, description, all_warehouses, eway_bill_admin, eway_bill_filling, supply_sheet)
                )
                role_id = cursor.lastrowid

            for state in order_states:
                mysql_manager.execute_query(
                    "INSERT IGNORE INTO role_order_states (role_id, state_name) VALUES (%s,%s)",
                    (role_id, state), fetch=False
                )
            for upload in uploads:
                mysql_manager.execute_query(
                    "INSERT IGNORE INTO role_uploads (role_id, upload_type) VALUES (%s,%s)",
                    (role_id, upload), fetch=False
                )
            flash(f'Role "{name}" created successfully.', 'success')
            return redirect(url_for('rolemanagement.index'))

        return self.render('admin/role_form.html', role=None,
                           all_order_states=ALL_ORDER_STATES,
                           all_upload_types=ALL_UPLOAD_TYPES)

    @expose('/edit/<int:role_id>', methods=['GET', 'POST'])
    def edit(self, role_id):
        from .db_manager import ALL_ORDER_STATES, ALL_UPLOAD_TYPES
        role = mysql_manager.execute_query(
            "SELECT role_id, name, description, all_warehouses, eway_bill_admin, eway_bill_filling, supply_sheet FROM roles WHERE role_id=%s", (role_id,)
        )
        if not role:
            flash('Role not found.', 'danger')
            return redirect(url_for('rolemanagement.index'))
        role = role[0]

        if request.method == 'POST':
            description = request.form.get('description', '').strip()
            all_warehouses = request.form.get('all_warehouses') == '1'
            eway_bill_admin = request.form.get('eway_bill_admin') == '1'
            eway_bill_filling = request.form.get('eway_bill_filling') == '1'
            supply_sheet = request.form.get('supply_sheet') == '1'
            order_states = request.form.getlist('order_states')
            uploads = request.form.getlist('uploads')

            mysql_manager.execute_query(
                "UPDATE roles SET description=%s, all_warehouses=%s, eway_bill_admin=%s, eway_bill_filling=%s, supply_sheet=%s WHERE role_id=%s",
                (description, all_warehouses, eway_bill_admin, eway_bill_filling, supply_sheet, role_id), fetch=False
            )
            # Replace permissions
            mysql_manager.execute_query(
                "DELETE FROM role_order_states WHERE role_id=%s", (role_id,), fetch=False
            )
            mysql_manager.execute_query(
                "DELETE FROM role_uploads WHERE role_id=%s", (role_id,), fetch=False
            )
            for state in order_states:
                mysql_manager.execute_query(
                    "INSERT IGNORE INTO role_order_states (role_id, state_name) VALUES (%s,%s)",
                    (role_id, state), fetch=False
                )
            for upload in uploads:
                mysql_manager.execute_query(
                    "INSERT IGNORE INTO role_uploads (role_id, upload_type) VALUES (%s,%s)",
                    (role_id, upload), fetch=False
                )
            flash(f'Role "{role["name"]}" updated.', 'success')
            return redirect(url_for('rolemanagement.index'))

        # Load current permissions for pre-filling checkboxes
        states = mysql_manager.execute_query(
            "SELECT state_name FROM role_order_states WHERE role_id=%s", (role_id,)
        )
        uploads_cur = mysql_manager.execute_query(
            "SELECT upload_type FROM role_uploads WHERE role_id=%s", (role_id,)
        )
        role['order_states'] = [r['state_name'] for r in states]
        role['uploads'] = [r['upload_type'] for r in uploads_cur]

        return self.render('admin/role_form.html', role=role,
                           all_order_states=ALL_ORDER_STATES,
                           all_upload_types=ALL_UPLOAD_TYPES)

    @expose('/delete/<int:role_id>', methods=['POST'])
    def delete(self, role_id):
        role = mysql_manager.execute_query(
            "SELECT name FROM roles WHERE role_id=%s", (role_id,)
        )
        if not role:
            flash('Role not found.', 'danger')
            return redirect(url_for('rolemanagement.index'))

        role_name = role[0]['name']
        users_with_role = mysql_manager.execute_query(
            "SELECT COUNT(*) as cnt FROM users WHERE role=%s", (role_name,)
        )
        if users_with_role and users_with_role[0]['cnt'] > 0:
            flash(f'Cannot delete "{role_name}" — {users_with_role[0]["cnt"]} user(s) have this role. Reassign them first.', 'danger')
            return redirect(url_for('rolemanagement.index'))

        mysql_manager.execute_query(
            "DELETE FROM roles WHERE role_id=%s", (role_id,), fetch=False
        )
        flash(f'Role "{role_name}" deleted.', 'success')
        return redirect(url_for('rolemanagement.index'))


# ──────────────────────────────────────────────
# Register everything
# ──────────────────────────────────────────────

def init_admin(app):
    admin = Admin(
        app,
        name='WMS Admin',
        template_mode='bootstrap4',
        index_view=SecureAdminIndexView(name='Dashboard', url='/admin'),
        base_template='admin/base_custom.html'
    )
    admin.add_view(RoleManagementView(name='Roles', endpoint='rolemanagement', category='Management'))
    admin.add_view(UserManagementView(name='Users', endpoint='usermanagement', category='Management'))
    admin.add_view(AccessManagementView(name='Warehouse Access', endpoint='accessmanagement', category='Management'))
    return admin
