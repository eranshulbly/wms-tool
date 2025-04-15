import { dashboard } from './dashboard';
import { utilities } from './utilities';
import { other } from './other';
import warehouse from './warehouse'; // Import the new warehouse menu

//-----------------------|| MENU ITEMS ||-----------------------//

const menuItems = {
    items: [dashboard,warehouse, utilities, other]
};

export default menuItems;
