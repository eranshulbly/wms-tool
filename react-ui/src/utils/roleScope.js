// Scoped roles: accounts that may see a fixed set of pages and nothing else.
//
// One table drives all three places the restriction shows up — the launcher tiles, the
// sidebar items, and the route guard. They used to be three separate `role ===` tests,
// which is how a role ends up hidden in two of them and reachable in the third.
//
// `menuIds` and `paths` are LISTS because a scope is not always a single screen. The
// part-convertor and DMS operator each get one; the ops manager runs the whole order desk
// and needs five. A single-screen role is just a list of one, so there is one shape here
// rather than two code paths that can drift apart.
//
// This is presentation only. The same scopes are enforced server-side in
// api/shared/auth.py, because hiding a menu does not stop anyone calling the API with
// their own token; these entries and that allowlist have to be kept in step.
export const SCOPED_ROLES = {
    part_convertor: {
        // Reads paper-order photos and uploads the sheet that turns them into order lines.
        home: '/warehouse/submitted-orders',
        menuIds: ['submitted-orders'],
        paths: ['/warehouse/submitted-orders'],
        title: 'Submitted Orders',
        description: 'Review submitted (photo / app) orders and build part-convertor sheets.'
    },
    dms_operator: {
        // Uploads stock, downloads DMS files, raises manual orders, rejects bad ones.
        home: '/warehouse/download-dms',
        menuIds: ['download-dms'],
        paths: ['/warehouse/download-dms'],
        title: 'Download DMS Input',
        description: 'Upload inventory, then generate and download DMS input files.'
    },
    ebco_opsmanager: {
        // The order desk end to end: orders in, through their states, picked, billed.
        // Lands on the dashboard because that is the screen that says what needs doing.
        home: '/dashboard/default',
        menuIds: [
            'default',              // Dashboard
            'upload-orders',
            'upload-invoices',
            'manage-orders',
            'download-picklist'
        ],
        paths: [
            '/dashboard/default',
            '/warehouse/upload-orders',
            '/warehouse/upload-invoices',
            '/warehouse/manage-orders',
            '/warehouse/download-picklist'
        ],
        title: 'Order Tracking',
        description: 'Upload orders and invoices, manage orders, and download picklists.'
    }
};

// Kept under its old name so nothing that imported it breaks. The two original entries
// are still single-screen; the name is simply no longer true of every row.
export const SINGLE_SCREEN_ROLES = SCOPED_ROLES;

// The scope this role is confined to, or null when the role is unrestricted.
export const scopeForRole = (role) => SCOPED_ROLES[role] || null;

// Whether a scoped role may open this path. Matched by prefix against each allowed path,
// so '/warehouse/manage-orders/42' is inside '/warehouse/manage-orders' — but
// '/warehouse/upload-products' is NOT inside '/warehouse/upload-orders', because the
// comparison is per entry rather than against a shared stem.
export const scopeAllowsPath = (scope, pathname) =>
    !!scope && (scope.paths || []).some((p) => pathname.startsWith(p));
