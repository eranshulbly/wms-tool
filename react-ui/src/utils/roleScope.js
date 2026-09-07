// Single-screen roles: accounts that may see exactly one page and nothing else.
//
// One table drives all three places the restriction shows up — the launcher tiles, the
// sidebar items, and the route guard. They used to be three separate `role ===` tests,
// which is how a role ends up hidden in two of them and reachable in the third.
//
// This is presentation only. The same scopes are enforced server-side in
// api/shared/auth.py, because hiding a menu does not stop anyone calling the API with
// their own token; these entries and that allowlist have to be kept in step.
export const SINGLE_SCREEN_ROLES = {
    part_convertor: {
        // Reads paper-order photos and uploads the sheet that turns them into order lines.
        // The standalone review page was merged into Submitted Orders (formerly
        // "Download DMS/Marg Input"), so this role lands there.
        home: '/warehouse/download-dms',
        menuId: 'download-dms',
        title: 'Submitted Orders',
        description: 'Review submitted (photo / app) orders and build part-convertor sheets.'
    },
    dms_operator: {
        // Uploads stock, downloads DMS files, raises manual orders, rejects bad ones.
        home: '/warehouse/download-dms',
        menuId: 'download-dms',
        title: 'Submitted Orders',
        description: 'Upload inventory, then generate and download DMS input files.'
    }
};

// The one screen this role is confined to, or null when the role is unrestricted.
export const scopeForRole = (role) => SINGLE_SCREEN_ROLES[role] || null;
