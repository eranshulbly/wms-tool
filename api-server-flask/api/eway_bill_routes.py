# -*- encoding: utf-8 -*-

from flask import request, send_file
from flask_restx import Resource, fields
from datetime import datetime
import pandas as pd
import openpyxl
import io
import json

from .models import (
    TransportRoute, RouteCity, CustomerCityMapping,
    DailyRouteManifest, CompanySchemaMapping
)
from .routes import rest_api, token_required, active_required

# --- Basic response models ---
basic_response = rest_api.model('EwayBasicResponse', {
    'success': fields.Boolean,
    'msg': fields.String
})

# ─────────────────────────────────────────────────────────────
# ROUTES  (with embedded cities)
# ─────────────────────────────────────────────────────────────

@rest_api.route('/api/eway/routes')
class EwayRoutes(Resource):
    @token_required
    @active_required
    def get(self, current_user):
        try:
            routes = TransportRoute.get_all()
            return {'success': True, 'routes': [r.to_dict() for r in routes]}, 200
        except Exception as e:
            return {'success': False, 'msg': str(e), 'routes': []}, 400

    @token_required
    @active_required
    def post(self, current_user):
        """Create a route; optionally seed cities in one call."""
        try:
            data = request.json
            route = TransportRoute(name=data['name'], description=data.get('description', ''))
            route.save()
            # Optionally seed cities immediately
            for city_name in data.get('cities', []):
                city_name = city_name.strip()
                if city_name:
                    RouteCity(route_id=route.route_id, city_name=city_name).save()
            return {'success': True, 'msg': 'Route created', 'route_id': route.route_id}, 200
        except Exception as e:
            return {'success': False, 'msg': str(e)}, 400


# ─────────────────────────────────────────────────────────────
# ROUTE CITIES  (add / list / remove individual cities)
# ─────────────────────────────────────────────────────────────

@rest_api.route('/api/eway/route-cities')
class EwayRouteCities(Resource):
    @token_required
    @active_required
    def get(self, current_user):
        """Return all cities across all routes."""
        try:
            cities = RouteCity.get_all_cities()
            return {'success': True, 'cities': cities}, 200
        except Exception as e:
            return {'success': False, 'msg': str(e)}, 400

    @token_required
    @active_required
    def post(self, current_user):
        """Add a single city to a route."""
        try:
            data = request.json
            city = RouteCity(route_id=data['route_id'], city_name=data['city_name'].strip())
            city.save()
            return {'success': True, 'msg': f"City '{data['city_name']}' added to route"}, 200
        except Exception as e:
            return {'success': False, 'msg': str(e)}, 400


@rest_api.route('/api/eway/route-cities/delete')
class EwayRouteCityDelete(Resource):
    @token_required
    @active_required
    def post(self, current_user):
        """Remove a city from a route by route_id + city_name."""
        try:
            data = request.json
            city = RouteCity(route_id=data['route_id'], city_name=data['city_name'])
            city.delete()
            return {'success': True, 'msg': 'City removed'}, 200
        except Exception as e:
            return {'success': False, 'msg': str(e)}, 400


# ─────────────────────────────────────────────────────────────
# CUSTOMER → CITY MAPPINGS
# ─────────────────────────────────────────────────────────────

@rest_api.route('/api/eway/customer-city-mappings')
class EwayCustomerCityMappings(Resource):
    @token_required
    @active_required
    def get(self, current_user):
        try:
            mappings = CustomerCityMapping.get_all()
            # Strip unserializable datetime fields before returning JSON
            clean = [
                {k: v for k, v in m.items() if not hasattr(v, 'isoformat')}
                for m in mappings
            ]
            return {'success': True, 'mappings': clean}, 200
        except Exception as e:
            return {'success': False, 'msg': str(e)}, 400

    @token_required
    @active_required
    def post(self, current_user):
        """Add / update a single customer-city mapping (upsert)."""
        try:
            data = request.json
            m = CustomerCityMapping(
                customer_code=data['customer_code'].strip(),
                customer_name=data.get('customer_name', '').strip(),
                city_name=data['city_name'].strip(),
                distance=int(data['distance'])
            )
            m.save()
            return {'success': True, 'msg': 'Mapping saved'}, 200
        except Exception as e:
            return {'success': False, 'msg': str(e)}, 400


@rest_api.route('/api/eway/customer-city-mappings/bulk')
class EwayCustomerCityMappingsBulk(Resource):
    @token_required
    @active_required
    def post(self, current_user):
        """
        Bulk-import customer→city mappings from an Excel file.
        Expected columns (case-insensitive):
          Customer Code | Customer Name | City | Distance (km)
        """
        try:
            if 'file' not in request.files:
                return {'success': False, 'msg': 'No file uploaded'}, 400
            f = request.files['file']
            wb = openpyxl.load_workbook(f, read_only=True, data_only=True)
            ws = wb.active

            # Read header row
            rows = list(ws.iter_rows(values_only=True))
            if not rows:
                return {'success': False, 'msg': 'Empty file'}, 400

            headers = [str(h).strip().lower() if h else '' for h in rows[0]]

            def col(name):
                aliases = {
                    'customer code': ['customer code', 'customer_code', 'code', 'cust code'],
                    'customer name': ['customer name', 'customer_name', 'name', 'account name'],
                    'city': ['city', 'city name', 'city_name', 'town'],
                    'distance': ['distance (km)', 'distance', 'dist km', 'dist', 'km'],
                }
                for a in aliases.get(name, [name]):
                    if a in headers:
                        return headers.index(a)
                return None

            ci_code = col('customer code')
            ci_name = col('customer name')
            ci_city = col('city')
            ci_dist = col('distance')

            if ci_code is None or ci_city is None or ci_dist is None:
                return {
                    'success': False,
                    'msg': 'Could not find required columns. Expected: Customer Code, City, Distance (km)'
                }, 400

            imported = 0
            errors = []
            for i, row in enumerate(rows[1:], start=2):
                try:
                    code = str(row[ci_code]).strip() if row[ci_code] else ''
                    city = str(row[ci_city]).strip() if row[ci_city] else ''
                    dist = row[ci_dist]
                    if not code or not city or dist is None:
                        continue
                    name = str(row[ci_name]).strip() if (ci_name is not None and row[ci_name]) else ''
                    m = CustomerCityMapping(
                        customer_code=code,
                        customer_name=name,
                        city_name=city,
                        distance=int(float(str(dist)))
                    )
                    m.save()
                    imported += 1
                except Exception as row_err:
                    errors.append(f"Row {i}: {str(row_err)}")

            return {
                'success': True,
                'imported': imported,
                'errors': errors,
                'msg': f"Imported {imported} mappings" + (f" ({len(errors)} errors)" if errors else "")
            }, 200
        except Exception as e:
            return {'success': False, 'msg': str(e)}, 400


@rest_api.route('/api/eway/customer-city-mappings/template')
class EwayCustomerCityTemplate(Resource):
    @token_required
    @active_required
    def get(self, current_user):
        """Download a sample Excel template for bulk upload."""
        try:
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Customer City Mapping"
            ws.append(['Customer Code', 'Customer Name', 'City', 'Distance (km)'])
            ws.append(['HMC001', 'Hero Moto Corp - Delhi', 'Pilibhit', 120])
            ws.append(['HMC002', 'Hero Moto Corp - UP', 'Badaun', 85])
            ws.column_dimensions['A'].width = 18
            ws.column_dimensions['B'].width = 35
            ws.column_dimensions['C'].width = 20
            ws.column_dimensions['D'].width = 16

            buf = io.BytesIO()
            wb.save(buf)
            buf.seek(0)
            return send_file(buf, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                             as_attachment=True, download_name='customer_city_mapping_template.xlsx')
        except Exception as e:
            return {'success': False, 'msg': str(e)}, 400


# ─────────────────────────────────────────────────────────────
# DAILY MANIFEST
# ─────────────────────────────────────────────────────────────

@rest_api.route('/api/eway/manifest')
class EwayManifest(Resource):
    @token_required
    @active_required
    def get(self, current_user):
        try:
            date_str = request.args.get('date', datetime.utcnow().strftime('%Y-%m-%d'))
            manifests = DailyRouteManifest.get_for_date(date_str)
            # Enrich each manifest with its cities and customer count
            enriched = []
            for m in (manifests or []):
                cities = RouteCity.get_for_route(m['route_id'])
                enriched.append({**m, 'cities': cities, 'city_count': len(cities)})
            return {'success': True, 'manifests': enriched}, 200
        except Exception as e:
            return {'success': False, 'msg': str(e)}, 400

    @token_required
    @active_required
    def post(self, current_user):
        try:
            data = request.json
            date_str = data.get('date', datetime.utcnow().strftime('%Y-%m-%d'))
            for asg in data.get('assignments', []):
                DailyRouteManifest(
                    route_id=asg['route_id'],
                    vehicle_number=asg['vehicle_number'],
                    manifest_date=date_str
                ).save()
            return {'success': True, 'msg': 'Daily manifest saved'}, 200
        except Exception as e:
            return {'success': False, 'msg': str(e)}, 400


# ─────────────────────────────────────────────────────────────
# CSV UPLOAD  — enriches rows via Customer → City → Route → Vehicle
# ─────────────────────────────────────────────────────────────

@rest_api.route('/api/eway/upload')
class EwayUpload(Resource):
    @token_required
    @active_required
    def post(self, current_user):
        try:
            if 'file' not in request.files:
                return {'success': False, 'msg': 'No file uploaded'}, 400
            file = request.files['file']
            if not file.filename:
                return {'success': False, 'msg': 'No file selected'}, 400

            company_id = request.form.get('company_id', type=int)
            if not company_id:
                return {'success': False, 'msg': 'company_id is required'}, 400

            schema = CompanySchemaMapping.get_for_company(company_id)
            if not schema:
                return {'success': False, 'msg': 'No schema found for this company. Configure it in Company Schema Config tab.'}, 400

            # Parse CSV
            raw = file.read()
            sep = '\t' if b'\t' in raw[:500] else ','
            df = pd.read_csv(io.BytesIO(raw), sep=sep)

            irn_col          = schema['irn_col']
            ccode_col        = schema['customer_code_col']
            cname_col        = schema['customer_name_col']
            invoice_col      = schema['invoice_no_col']

            missing = [c for c in [irn_col, ccode_col, cname_col, invoice_col] if c not in df.columns]
            if missing:
                return {'success': False, 'msg': f"CSV columns not found: {', '.join(missing)}"}, 400

            today = datetime.utcnow().strftime('%Y-%m-%d')
            results = []

            for _, row in df.iterrows():
                irn = str(row.get(irn_col, '') or '').strip()
                if not irn or irn.lower() == 'nan':
                    continue  # Only rows with an IRN are e-invoices

                c_code   = str(row.get(ccode_col,   '') or '').strip()
                c_name   = str(row.get(cname_col,   '') or '').strip()
                inv_no   = str(row.get(invoice_col, '') or '').strip()

                city_name     = None
                route_id      = None
                vehicle_no    = None
                distance      = None

                # Lookup: Customer Code → city + distance
                cm = CustomerCityMapping.find_by_customer_code(c_code)
                if cm:
                    city_name = cm.city_name
                    distance  = cm.distance
                    # Lookup: city → route_id
                    route_id = RouteCity.find_route_by_city(city_name)
                    if route_id:
                        # Lookup: route + date → vehicle
                        vehicle_no = DailyRouteManifest.get_vehicle_for_route_date(route_id, today)

                status = 'Complete' if (distance and vehicle_no) else 'Incomplete'
                results.append({
                    'invoice_no':    inv_no,
                    'customer_code': c_code,
                    'customer_name': c_name,
                    'irn':           irn,
                    'city':          city_name,
                    'distance':      distance,
                    'vehicle_no':    vehicle_no,
                    'route_id':      route_id,
                    'status':        status
                })

            return {'success': True, 'data': results}, 200
        except Exception as e:
            return {'success': False, 'msg': str(e)}, 400


# ─────────────────────────────────────────────────────────────
# JSON GENERATION
# ─────────────────────────────────────────────────────────────

@rest_api.route('/api/eway/generate-json')
class EwayGenerateJson(Resource):
    @token_required
    @active_required
    def post(self, current_user):
        try:
            data = request.json
            payload = []
            for item in data:
                if not item.get('irn') or not item.get('vehicle_no') or not item.get('distance'):
                    return {'success': False, 'msg': 'Missing IRN, Vehicle No, or Distance in one or more rows.'}, 400
                payload.append({
                    "Irn":           item['irn'],
                    "Distance":      int(item['distance']),
                    "TransporterId": "",
                    "TransDocNo":    "",
                    "TransDocDate":  "",
                    "VehicleNo":     item['vehicle_no'],
                    "VehType":       "R"
                })
            return {'success': True, 'json_payload': payload, 'msg': f'Generated {len(payload)} records.'}, 200
        except Exception as e:
            return {'success': False, 'msg': str(e)}, 400


# ─────────────────────────────────────────────────────────────
# SCHEMA MAPPINGS  (company CSV column config)
# ─────────────────────────────────────────────────────────────

@rest_api.route('/api/eway/schema-mappings')
class EwaySchemaMappings(Resource):
    @token_required
    @active_required
    def get(self, current_user):
        try:
            company_id = request.args.get('company_id', type=int)
            if not company_id:
                return {'success': False, 'msg': 'company_id is required'}, 400
            schema = CompanySchemaMapping.get_for_company(company_id)
            return {'success': True, 'schema': schema}, 200
        except Exception as e:
            return {'success': False, 'msg': str(e)}, 400

    @token_required
    @active_required
    def post(self, current_user):
        try:
            data = request.json
            schema = CompanySchemaMapping(
                company_id=data['company_id'],
                invoice_no_col=data['invoice_no_col'],
                customer_code_col=data['customer_code_col'],
                customer_name_col=data['customer_name_col'],
                irn_col=data['irn_col'],
                amount_col=data.get('amount_col', '')
            )
            schema.save()
            return {'success': True, 'msg': 'Schema saved'}, 200
        except Exception as e:
            return {'success': False, 'msg': str(e)}, 400
