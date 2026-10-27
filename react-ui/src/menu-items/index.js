import home from './home';
import warehouse from './warehouse';
import eway from './eway';
import supply from './supply';
import analytics from './analytics';
import adminMenu from './admin';
import poBuilder from './poBuilder';

//-----------------------|| MENU ITEMS ||-----------------------//

// Full set of groups (used by Breadcrumbs). The sidebar itself renders only the
// group relevant to the current section — see Sidebar/MenuList.
const menuItems = {
    items: [home, warehouse, eway, supply, analytics, adminMenu, poBuilder]
};

// Which section a given route belongs to. Keys are section group ids above.
export const SECTION_FOR_PATH = [
    { match: (p) => p.startsWith('/admin'), section: 'admin' },
    // Monthly Data Upload lives under the Admin section (shown in the Admin sidebar group).
    { match: (p) => p.startsWith('/monthly-data-upload'), section: 'admin' },
    // Inventory Ingestion likewise. Without an entry here sectionForPath returns null and
    // MenuList finds no group to render, so the whole sidebar comes up empty — the page
    // still works, but the user loses all navigation.
    { match: (p) => p.startsWith('/inventory-ingestion'), section: 'admin' },
    // Outstanding Check is NOT in the Admin menu group (it has its own Launcher tile
    // instead), so no entry here maps it to 'admin' — sectionForPath returns null for
    // it and the sidebar shows just the Home link, same as a page with no group at all.
    { match: (p) => p.startsWith('/po-builder'), section: 'po-builder' },
    { match: (p) => p.startsWith('/analytics'), section: 'analytics' },
    { match: (p) => p === '/warehouse/eway-bill', section: 'eway' },
    { match: (p) => p === '/warehouse/supply-sheet', section: 'supply' },
    {
        match: (p) => p.startsWith('/dashboard') || p.startsWith('/warehouse'),
        section: 'order-tracking'
    }
];

export function sectionForPath(pathname) {
    const hit = SECTION_FOR_PATH.find((r) => r.match(pathname));
    return hit ? hit.section : null;
}

export default menuItems;
