import home from './home';
import warehouse from './warehouse';
import eway from './eway';
import supply from './supply';
import analytics from './analytics';
import adminMenu from './admin';

//-----------------------|| MENU ITEMS ||-----------------------//

// Full set of groups (used by Breadcrumbs). The sidebar itself renders only the
// group relevant to the current section — see Sidebar/MenuList.
const menuItems = {
    items: [home, warehouse, eway, supply, analytics, adminMenu]
};

// Which section a given route belongs to. Keys are section group ids above.
export const SECTION_FOR_PATH = [
    { match: (p) => p.startsWith('/admin'), section: 'admin' },
    // Inventory Ingestion. Without an entry here sectionForPath returns null and
    // MenuList finds no group to render, so the whole sidebar comes up empty — the page
    // still works, but the user loses all navigation.
    { match: (p) => p.startsWith('/inventory-ingestion'), section: 'admin' },
    // Margin Check. Same rule as Inventory Ingestion above: without an entry the
    // sidebar renders no group at all and the page loses its navigation.
    { match: (p) => p.startsWith('/margin-check'), section: 'admin' },
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
