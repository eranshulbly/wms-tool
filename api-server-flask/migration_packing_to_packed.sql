-- Migration: rename order status from Packing to Packed
UPDATE potential_orders SET status = 'Packed' WHERE status = 'Packing';
UPDATE order_state SET state_name = 'Packed', description = 'Order items are packed' WHERE state_name = 'Packing';
UPDATE order_state_history SET state_name = 'Packed' WHERE state_name = 'Packing';
UPDATE role_order_states SET state_name = 'Packed' WHERE state_name = 'Packing';

-- Migration: rename order status from Invoice Ready to Invoiced
UPDATE potential_orders SET status = 'Invoiced' WHERE status = 'Invoice Ready';
UPDATE order_state SET state_name = 'Invoiced', description = 'Order invoiced and ready for dispatch' WHERE state_name = 'Invoice Ready';
UPDATE order_state_history SET state_name = 'Invoiced' WHERE state_name = 'Invoice Ready';
UPDATE role_order_states SET state_name = 'Invoiced' WHERE state_name = 'Invoice Ready';
