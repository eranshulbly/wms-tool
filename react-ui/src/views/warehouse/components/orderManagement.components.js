import React, { useState, useEffect } from 'react';
import {
  Grid,
  Card,
  CardContent,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Paper,
  CircularProgress,
  Box,
  Button,
  Chip,
  Typography,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  Stepper,
  Step,
  StepLabel,
  Divider,
  List,
  ListItem,
  ListItemText,
  IconButton,
  Accordion,
  AccordionSummary,
  AccordionDetails
} from '@material-ui/core';
import {
  IconArrowRight,
  IconPackage,
  IconBox,
  IconPlus,
  IconCheck,
  IconTruck,
  IconMinus,
  IconChevronDown
} from '@tabler/icons';
import { STATUS_FILTER_OPTIONS, STATUS_LABELS, TABLE_COLUMNS } from '../constants/orderManagement.constants';
import { formatDate, getTimeInCurrentStatus, getNextStatus, getStatusChipClass } from '../utils/orderManagement.utils';
// Import orderManagementService at the top of orderManagement.components.js
import orderManagementService from '../../../services/orderManagementService';

/**
 * Filter Controls Component
 */
export const FilterControls = ({
  warehouses,
  companies,
  warehouse,
  company,
  statusFilter,
  onWarehouseChange,
  onCompanyChange,
  onStatusFilterChange,
  classes
}) => (
  <Grid item xs={12} className={classes.orderFilterContainer}>
    <Card>
      <CardContent>
        <Grid container spacing={2}>
          <Grid item xs={12} md={4} lg={3}>
            <FormControl variant="outlined" className={classes.formControl} fullWidth>
              <InputLabel id="warehouse-select-label">Warehouse</InputLabel>
              <Select
                labelId="warehouse-select-label"
                id="warehouse-select"
                value={warehouse}
                onChange={onWarehouseChange}
                label="Warehouse"
              >
                {warehouses.map((wh) => {
                  const warehouseId = wh.warehouse_id !== undefined ? wh.warehouse_id : wh.id;
                  return (
                    <MenuItem key={warehouseId} value={warehouseId}>
                      {wh.name}
                    </MenuItem>
                  );
                })}
              </Select>
            </FormControl>
          </Grid>
          <Grid item xs={12} md={4} lg={3}>
            <FormControl variant="outlined" className={classes.formControl} fullWidth>
              <InputLabel id="company-select-label">Company</InputLabel>
              <Select
                labelId="company-select-label"
                id="company-select"
                value={company}
                onChange={onCompanyChange}
                label="Company"
              >
                {companies.map((comp) => {
                  const companyId = comp.company_id !== undefined ? comp.company_id : comp.id;
                  return (
                    <MenuItem key={companyId} value={companyId}>
                      {comp.name}
                    </MenuItem>
                  );
                })}
              </Select>
            </FormControl>
          </Grid>
          <Grid item xs={12} md={4} lg={3}>
            <FormControl variant="outlined" className={classes.formControl} fullWidth>
              <InputLabel id="status-select-label">Order Status</InputLabel>
              <Select
                labelId="status-select-label"
                id="status-select"
                value={statusFilter}
                onChange={onStatusFilterChange}
                label="Order Status"
              >
                {STATUS_FILTER_OPTIONS.map((option) => (
                  <MenuItem key={option.value} value={option.value}>
                    {option.label}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          </Grid>
        </Grid>
      </CardContent>
    </Card>
  </Grid>
);

/**
 * Status Chip Component
 */
export const StatusChip = ({ status, classes }) => {
  const normalizedStatus = String(status).toLowerCase().replace(/\s+/g, '-');
  const className = classes[getStatusChipClass(normalizedStatus)]; // This will now use the updated function

  return (
    <Chip
      label={STATUS_LABELS[normalizedStatus] || normalizedStatus}
      className={`${classes.statusChip} ${className}`}
      size="small"
    />
  );
};


// FIXED: Correct Status Progression
const CORRECT_STATUS_PROGRESSION = {
  'open': { next: 'picking', label: 'Start Picking' },
  'picking': { next: 'packing', label: 'Start Packing' },
  'packing': { next: 'dispatch-ready', label: 'Ready for Dispatch' }, // Changed
  'dispatch-ready': { next: 'completed', label: 'Complete Dispatch' },
  'completed': null,
  'partially-completed': null
};

/**
 * FIXED: Status Action Button with Correct Flow
 */
export const StatusActionButton = ({ order, onStatusUpdate, classes }) => {
  const currentStatus = order.status?.toLowerCase().replace(/\s+/g, '-');
  const nextAction = CORRECT_STATUS_PROGRESSION[currentStatus];

  if (!nextAction) return null;

  const handleClick = (e) => {
    e.stopPropagation();

    // Different handling based on status transition
    if (currentStatus === 'packing') {
      // This requires the packing dialog to handle dispatch ready
      onStatusUpdate(order, 'packing-to-dispatch');
    } else if (currentStatus === 'dispatch-ready') {
      // Complete dispatch
      onStatusUpdate(order, 'complete-dispatch');
    } else {
      // Regular status update
      onStatusUpdate(order, nextAction.next);
    }
  };

  return (
    <Button
      variant="outlined"
      color="primary"
      size="small"
      className={classes.statusActionButton}
      onClick={handleClick}
      startIcon={<IconArrowRight size={16} />}
    >
      {nextAction.label}
    </Button>
  );
};


/**
 * Orders Table Component
 */
export const OrdersTable = ({
  orders,
  loading,
  statusFilter,
  onOrderClick,
  onStatusUpdate,
  classes
}) => (
  <Grid item xs={12}>
    <Card>
      <CardContent>
        <Typography variant="h4" gutterBottom>
          Orders
          {statusFilter !== 'all' && (
            <Typography
              variant="subtitle1"
              component="span"
              className={classes.filterTitle}
            >
              - Showing {STATUS_FILTER_OPTIONS.find(opt => opt.value === statusFilter)?.label} ({orders.length} orders)
            </Typography>
          )}
        </Typography>

        {loading ? (
          <Box className={classes.loadingContainer}>
            <CircularProgress />
          </Box>
        ) : (
          <TableContainer className={classes.tableContainer} component={Paper}>
            <Table stickyHeader aria-label="orders table">
              <TableHead>
                <TableRow>
                  {TABLE_COLUMNS.map((column) => (
                    <TableCell key={column.id}>{column.label}</TableCell>
                  ))}
                </TableRow>
              </TableHead>
              <TableBody>
                {orders.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={TABLE_COLUMNS.length} align="center">
                      <Typography variant="subtitle1">No orders found</Typography>
                    </TableCell>
                  </TableRow>
                ) : (
                  orders.map((order) => (
                    <TableRow
                      key={order.order_request_id}
                      hover
                      onClick={() => onOrderClick(order)}
                      className={classes.tableRow}
                    >
                      <TableCell>{order.dealer_name}</TableCell>
                      <TableCell>
                        <StatusChip status={order.status} classes={classes} />
                      </TableCell>
                      <TableCell>{formatDate(order.order_date)}</TableCell>
                      <TableCell>{getTimeInCurrentStatus(order.current_state_time)}</TableCell>
                      <TableCell>{order.assigned_to || 'Unassigned'}</TableCell>
                      <TableCell>
                        <Box display="flex" alignItems="center">
                          <StatusActionButton
                            order={order}
                            onStatusUpdate={onStatusUpdate}
                            classes={classes}
                          />
                        </Box>
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </TableContainer>
        )}
      </CardContent>
    </Card>
  </Grid>
);

/**
 * FIXED: Product Packing Form with Proper Quantity Handling
 */
const ProductPackingForm = ({ products, boxes, onUpdateProducts, onUpdateBoxes, classes }) => {
  const [productQuantities, setProductQuantities] = useState({});
  const [productBoxAssignments, setProductBoxAssignments] = useState({});
  const [boxList, setBoxList] = useState(boxes || []);
  const [boxProductQuantities, setBoxProductQuantities] = useState({});

  useEffect(() => {
    // Initialize quantities and box assignments
    const initialQuantities = {};
    const initialAssignments = {};
    const initialBoxQuantities = {};

    products.forEach(product => {
      initialQuantities[product.product_id] = product.quantity_packed || 0;
      initialAssignments[product.product_id] = product.assigned_to_box || '';

      // Initialize box quantities for this product
      initialBoxQuantities[product.product_id] = {};
      boxList.forEach(box => {
        initialBoxQuantities[product.product_id][box.box_id] = 0;
      });
    });

    setProductQuantities(initialQuantities);
    setProductBoxAssignments(initialAssignments);
    setBoxProductQuantities(initialBoxQuantities);
  }, [products, boxList]);

  // FIXED: Proper keyboard input handling
  const handleBoxQuantityChange = (productId, boxId, value) => {
    let newQuantity;
    if (value === '' || value === null || value === undefined) {
      newQuantity = 0;
    } else {
      newQuantity = parseInt(value, 10);
      if (isNaN(newQuantity) || newQuantity < 0) {
        newQuantity = 0;
      }
    }

    // Update box quantities
    const newBoxQuantities = {
      ...boxProductQuantities,
      [productId]: {
        ...boxProductQuantities[productId],
        [boxId]: newQuantity
      }
    };
    setBoxProductQuantities(newBoxQuantities);

    // Calculate total packed quantity for this product across all boxes
    const totalPacked = Object.values(newBoxQuantities[productId] || {}).reduce((sum, qty) => {
      return sum + (parseInt(qty) || 0);
    }, 0);

    const newQuantities = { ...productQuantities, [productId]: totalPacked };
    setProductQuantities(newQuantities);

    // Update box assignments
    const newAssignments = { ...productBoxAssignments };
    const boxesWithProduct = Object.keys(newBoxQuantities[productId] || {}).filter(
      bId => (newBoxQuantities[productId][bId] || 0) > 0
    );

    if (boxesWithProduct.length > 0) {
      newAssignments[productId] = boxesWithProduct.join(',');
    } else {
      newAssignments[productId] = '';
    }

    setProductBoxAssignments(newAssignments);
    onUpdateProducts(newQuantities, newAssignments, newBoxQuantities);
  };

  const addNewBox = () => {
    const newBoxId = `B${Date.now()}`;
    const newBox = {
      box_id: newBoxId,
      box_name: `Box-${boxList.length + 1}`,
      products: []
    };
    const updatedBoxes = [...boxList, newBox];
    setBoxList(updatedBoxes);

    // Initialize quantities for all products in the new box
    const newBoxQuantities = { ...boxProductQuantities };
    const newQuantities = { ...productQuantities };
    const newAssignments = { ...productBoxAssignments };

    // If this is the first box, assign all available quantities
    if (boxList.length === 0) {
      products.forEach(product => {
        if (!newBoxQuantities[product.product_id]) {
          newBoxQuantities[product.product_id] = {};
        }

        // Set quantity to available quantity for first box
        const availableQty = product.quantity_available || product.quantity_ordered;
        newBoxQuantities[product.product_id][newBoxId] = availableQty;

        // Update total quantities and assignments
        newQuantities[product.product_id] = availableQty;
        newAssignments[product.product_id] = newBoxId;
      });
    } else {
      // For subsequent boxes, initialize with 0
      products.forEach(product => {
        if (!newBoxQuantities[product.product_id]) {
          newBoxQuantities[product.product_id] = {};
        }
        newBoxQuantities[product.product_id][newBoxId] = 0;
      });
    }

    setBoxProductQuantities(newBoxQuantities);
    setProductQuantities(newQuantities);
    setProductBoxAssignments(newAssignments);

    onUpdateProducts(newQuantities, newAssignments, newBoxQuantities);
    onUpdateBoxes(updatedBoxes);
  };

  const removeBox = (boxId) => {
    const updatedBoxes = boxList.filter(box => box.box_id !== boxId);
    setBoxList(updatedBoxes);

    // Remove quantities for this box and recalculate
    const newBoxQuantities = { ...boxProductQuantities };
    const newQuantities = { ...productQuantities };
    const newAssignments = { ...productBoxAssignments };

    products.forEach(product => {
      if (newBoxQuantities[product.product_id]) {
        delete newBoxQuantities[product.product_id][boxId];

        // Recalculate total for this product
        const totalPacked = Object.values(newBoxQuantities[product.product_id] || {}).reduce((sum, qty) => {
          return sum + (parseInt(qty) || 0);
        }, 0);
        newQuantities[product.product_id] = totalPacked;

        // Update assignment
        const boxesWithProduct = Object.keys(newBoxQuantities[product.product_id] || {}).filter(
          bId => (newBoxQuantities[product.product_id][bId] || 0) > 0
        );

        if (boxesWithProduct.length > 0) {
          newAssignments[product.product_id] = boxesWithProduct.join(',');
        } else {
          newAssignments[product.product_id] = '';
        }
      }
    });

    setBoxProductQuantities(newBoxQuantities);
    setProductQuantities(newQuantities);
    setProductBoxAssignments(newAssignments);

    onUpdateProducts(newQuantities, newAssignments, newBoxQuantities);
    onUpdateBoxes(updatedBoxes);
  };

  const getProductTotalInBoxes = (productId) => {
    return Object.values(boxProductQuantities[productId] || {}).reduce((sum, qty) => {
      return sum + (parseInt(qty) || 0);
    }, 0);
  };

  const getBoxTotalQuantity = (boxId) => {
    return products.reduce((total, product) => {
      const quantity = boxProductQuantities[product.product_id]?.[boxId] || 0;
      return total + (parseInt(quantity) || 0);
    }, 0);
  };

  // Rest of the component remains the same but with proper keyboard input handling
  return (
    <Box>
      <Typography variant="h6" gutterBottom>
        Product Packing Details
      </Typography>

      {/* Products Summary Table */}
      <TableContainer component={Paper} style={{ marginBottom: 16 }}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Product</TableCell>
              <TableCell>Ordered Qty</TableCell>
              <TableCell>Available Qty</TableCell>
              <TableCell>Total Packed</TableCell>
              <TableCell>Remaining</TableCell>
              <TableCell>Status</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {products.map((product) => {
              const totalInBoxes = getProductTotalInBoxes(product.product_id);
              const remaining = product.quantity_available - totalInBoxes;
              const hasAssignment = productBoxAssignments[product.product_id];
              const isValid = totalInBoxes <= product.quantity_available && (totalInBoxes === 0 || hasAssignment);

              return (
                <TableRow key={product.product_id}>
                  <TableCell>
                    <Typography variant="body2" fontWeight="bold">
                      {product.name}
                    </Typography>
                    <Typography variant="caption" color="textSecondary">
                      {product.product_string}
                    </Typography>
                  </TableCell>
                  <TableCell>{product.quantity_ordered}</TableCell>
                  <TableCell>{product.quantity_available}</TableCell>
                  <TableCell>
                    <Typography
                      variant="body2"
                      color={totalInBoxes > product.quantity_available ? "error" : "textPrimary"}
                      fontWeight="bold"
                    >
                      {totalInBoxes}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Typography
                      variant="body2"
                      color={remaining > 0 ? "warning" : "textSecondary"}
                      fontWeight={remaining > 0 ? "bold" : "normal"}
                    >
                      {remaining}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    {isValid ? (
                      <Chip size="small" label="Valid" style={{ backgroundColor: '#4caf50', color: 'white' }} />
                    ) : (
                      <Chip size="small" label="Invalid" style={{ backgroundColor: '#f44336', color: 'white' }} />
                    )}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </TableContainer>

      {/* Box Management */}
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={2}>
        <Typography variant="h6">
          Boxes ({boxList.length})
        </Typography>
        <Button
          variant="outlined"
          startIcon={<IconPlus size={16} />}
          onClick={addNewBox}
        >
          Add Box
        </Button>
      </Box>

      {/* Enhanced Boxes List with Fixed Quantity Input */}
      {boxList.map((box) => {
        const boxTotal = getBoxTotalQuantity(box.box_id);
        const productsInBox = products.filter(product => {
          const quantity = boxProductQuantities[product.product_id]?.[box.box_id] || 0;
          return parseInt(quantity) > 0;
        });

        return (
          <Accordion key={box.box_id} style={{ marginBottom: 8 }}>
            <AccordionSummary expandIcon={<IconChevronDown />}>
              <Box display="flex" alignItems="center" justifyContent="space-between" width="100%">
                <Box display="flex" alignItems="center">
                  <IconBox size={20} style={{ marginRight: 8 }} />
                  <Typography variant="subtitle1">
                    {box.box_name} ({boxTotal} total items, {productsInBox.length} products)
                  </Typography>
                </Box>
                <IconButton
                  size="small"
                  onClick={(e) => {
                    e.stopPropagation();
                    removeBox(box.box_id);
                  }}
                >
                  <IconMinus size={16} />
                </IconButton>
              </Box>
            </AccordionSummary>
            <AccordionDetails>
              <Box width="100%">
                <Typography variant="subtitle2" gutterBottom>
                  Product Quantities in {box.box_name}:
                </Typography>

                {products.map((product) => {
                  const currentQuantity = boxProductQuantities[product.product_id]?.[box.box_id] || 0;
                  const totalInAllBoxes = getProductTotalInBoxes(product.product_id);
                  const remainingForProduct = product.quantity_available - totalInAllBoxes + parseInt(currentQuantity);

                  return (
                    <Box key={product.product_id} className={classes.productInBox}>
                      <Box className={classes.productInBoxName}>
                        <Typography variant="body2" fontWeight="bold">
                          {product.name}
                        </Typography>
                        <Typography variant="caption" color="textSecondary">
                          Available: {remainingForProduct} | Total in all boxes: {totalInAllBoxes}
                        </Typography>
                      </Box>
                      <Box className={classes.productInBoxQuantity}>
                        <TextField
                          type="number"
                          size="small"
                          value={currentQuantity}
                          onChange={(e) => {
                            handleBoxQuantityChange(product.product_id, box.box_id, e.target.value);
                          }}
                          inputProps={{
                            min: 0,
                            max: remainingForProduct,
                            step: 1,
                            style: { width: '70px', textAlign: 'center' }
                          }}
                          error={currentQuantity > remainingForProduct}
                          helperText={currentQuantity > remainingForProduct ? 'Exceeds available' : ''}
                        />
                      </Box>
                    </Box>
                  );
                })}

                {boxTotal === 0 && (
                  <Typography color="textSecondary" style={{ fontStyle: 'italic', marginTop: 8 }}>
                    No products assigned to this box yet
                  </Typography>
                )}
              </Box>
            </AccordionDetails>
          </Accordion>
        );
      })}
    </Box>
  );
};

/**
 * FIXED: Enhanced Order Details Dialog with Correct Flow and Timeline
 */
export const OrderDetailsDialog = ({
  open,
  order,
  onClose,
  onStatusUpdate,
  classes
}) => {
  const [activeStep, setActiveStep] = useState(0);
  const [productQuantities, setProductQuantities] = useState({});
  const [productBoxAssignments, setProductBoxAssignments] = useState({});
  const [boxProductQuantities, setBoxProductQuantities] = useState({});
  const [boxes, setBoxes] = useState([]);
  const [loading, setLoading] = useState(false);
  const [showWarningDialog, setShowWarningDialog] = useState(false);
  const [warningMessages, setWarningMessages] = useState([]);

  // FIXED: Proper steps based on actual flow
  const steps = ['Order Details', 'Packing', 'Dispatch Ready', 'Completed'];

  useEffect(() => {
    if (order && order.products) {
      const quantities = {};
      const assignments = {};
      const boxQuantities = {};

      order.products.forEach(product => {
        quantities[product.product_id] = product.quantity_packed || 0;
        assignments[product.product_id] = product.assigned_to_box || '';
        boxQuantities[product.product_id] = {};
      });

      setProductQuantities(quantities);
      setProductBoxAssignments(assignments);
      setBoxProductQuantities(boxQuantities);
      setBoxes(order.boxes || []);

      // FIXED: Set active step based on correct status flow
      switch (order.status?.toLowerCase().replace(/\s+/g, '-')) {
        case 'open':
        case 'picking':
          setActiveStep(0);
          break;
        case 'packing':
          setActiveStep(1);
          break;
        case 'dispatch-ready':
          setActiveStep(2);
          break;
        case 'completed':
        case 'partially-completed':
          setActiveStep(3);
          break;
        default:
          setActiveStep(0);
      }
    }
  }, [order]);

  const handleUpdateProducts = (quantities, assignments, boxQuantities = null) => {
    setProductQuantities(quantities);
    setProductBoxAssignments(assignments);
    if (boxQuantities) {
      setBoxProductQuantities(boxQuantities);
    }
  };

  const handleUpdateBoxes = (updatedBoxes) => {
    setBoxes(updatedBoxes);
  };

  const validatePackingData = () => {
    const errors = [];
    const warnings = [];

    if (!order || !order.products) {
      errors.push('No products found in order');
      return { isValid: false, errors, warnings };
    }

    let hasPackedItems = false;
    let hasRemainingItems = false;

    order.products.forEach(product => {
      const quantity = productQuantities[product.product_id] || 0;
      const boxAssignment = productBoxAssignments[product.product_id];

      if (quantity > 0) {
        hasPackedItems = true;

        if (!boxAssignment) {
          errors.push(`${product.name} has packed quantity but no box assignment`);
        }

        if (quantity > product.quantity_available) {
          errors.push(`${product.name} exceeds available quantity`);
        }

        if (quantity < product.quantity_ordered) {
          hasRemainingItems = true;
          warnings.push(`${product.name} is partially packed (${quantity}/${product.quantity_ordered})`);
        }
      } else if (product.quantity_ordered > 0) {
        hasRemainingItems = true;
      }
    });

    if (!hasPackedItems) {
      errors.push('No products have been packed. Please pack at least one product.');
    }

    return {
      isValid: errors.length === 0,
      errors,
      warnings,
      hasRemainingItems
    };
  };

  // FIXED: Move to Dispatch Ready (creates final order)
  const handleMoveToDispatchReady = async () => {
    const validation = validatePackingData();

    if (!validation.isValid) {
      alert('Please fix the following errors before proceeding:\n\n' + validation.errors.join('\n'));
      return;
    }

    // Show warnings about partial completion
    if (validation.hasRemainingItems) {
      const proceed = window.confirm(
        'Some items will remain unpacked and will be marked as "Partially Completed".\n\n' +
        validation.warnings.join('\n') + '\n\n' +
        'Do you want to proceed?'
      );
      if (!proceed) return;
    }

    await moveToDispatchReady();
  };

  const moveToDispatchReady = async () => {
    setLoading(true);
    try {
      // Prepare data for moving to dispatch ready
      const productsData = order.products.map(product => ({
        product_id: product.product_id,
        quantity_packed: productQuantities[product.product_id] || 0,
        quantity_remaining: product.quantity_ordered - (productQuantities[product.product_id] || 0)
      }));

      const boxesData = boxes.map(box => ({
        box_id: box.box_id,
        box_name: box.box_name,
        products: order.products
            .filter(product =>
                productBoxAssignments[product.product_id] &&
                productBoxAssignments[product.product_id].includes(box.box_id) &&
                (boxProductQuantities[product.product_id]?.[box.box_id] || 0) > 0
            )
            .map(product => ({
              product_id: product.product_id,
              quantity: boxProductQuantities[product.product_id]?.[box.box_id] || 0
            }))
      })).filter(box => box.products.length > 0);

      // Use the service instead of direct fetch
      const result = await orderManagementService.moveToDispatchReady(
          order.order_request_id,
          productsData,
          boxesData
      );

      if (result.success) {
        setActiveStep(2); // Move to Dispatch Ready step

        const message = [
          'Order moved to Dispatch Ready!',
          `Final Order: ${result.final_order_number}`,
          `Packed Items: ${result.total_packed}`,
          result.total_remaining > 0 ? `Remaining Items: ${result.total_remaining}` : '',
          result.has_remaining_items ? 'Status: Partially Completed' : 'Status: Dispatch Ready'
        ].filter(Boolean).join('\n');

        alert(message);

        // Notify parent to refresh data
        if (onStatusUpdate) {
          onStatusUpdate(order, 'dispatch-ready');
        }
      } else {
        throw new Error(result.msg || 'Failed to move to dispatch ready');
      }
    } catch (error) {
      console.error('Error moving to dispatch ready:', error);
      alert('Error moving to dispatch ready: ' + error.message);
    } finally {
      setLoading(false);
    }
  };

  // FIXED: Complete Dispatch (mark as dispatched from warehouse)
  const handleCompleteDispatch = async () => {
    const proceed = window.confirm(
      'This will mark the order as completed and dispatched from the warehouse.\n\n' +
      'Are you sure you want to proceed?'
    );

    if (!proceed) return;

    setLoading(true);
    try {
      // Use the service instead of direct fetch
      const result = await orderManagementService.completeDispatch(order.order_request_id);

      if (result.success) {
        alert([
          'Order dispatched successfully!',
          `Order Number: ${result.final_order_number}`,
          `Dispatched: ${new Date(result.dispatched_date).toLocaleString()}`
        ].join('\n'));

        onClose(); // Close dialog

        // Refresh parent data
        if (onStatusUpdate) {
          onStatusUpdate(order, 'completed');
        }
      } else {
        throw new Error(result.msg || 'Failed to complete dispatch');
      }
    } catch (error) {
      console.error('Error completing dispatch:', error);
      alert('Error completing dispatch: ' + error.message);
    } finally {
      setLoading(false);
    }
  };


  const renderStepContent = () => {
    switch (activeStep) {
      case 0: // Order Details
        return (
          <Box>
            <Grid container spacing={2}>
              <Grid item xs={12} md={6}>
                <Typography variant="subtitle2" gutterBottom>Order ID:</Typography>
                <Typography variant="body1" gutterBottom>{order?.order_request_id}</Typography>
              </Grid>
              <Grid item xs={12} md={6}>
                <Typography variant="subtitle2" gutterBottom>Status:</Typography>
                <Chip
                  label={order?.status?.replace('-', ' ') || 'Unknown'}
                  color="primary"
                  size="small"
                />
              </Grid>
              <Grid item xs={12} md={6}>
                <Typography variant="subtitle2" gutterBottom>Dealer:</Typography>
                <Typography variant="body1" gutterBottom>{order?.dealer_name}</Typography>
              </Grid>
              <Grid item xs={12} md={6}>
                <Typography variant="subtitle2" gutterBottom>Order Date:</Typography>
                <Typography variant="body1" gutterBottom>
                  {order?.order_date ? new Date(order.order_date).toLocaleDateString() : 'N/A'}
                </Typography>
              </Grid>
            </Grid>

            <Divider style={{ margin: '16px 0' }} />

            <Typography variant="h6" gutterBottom>Products</Typography>
            <TableContainer component={Paper}>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Product</TableCell>
                    <TableCell>Description</TableCell>
                    <TableCell>Quantity</TableCell>
                    <TableCell>Price</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {order?.products?.map((product) => (
                    <TableRow key={product.product_id}>
                      <TableCell>
                        <Typography variant="body2" fontWeight="bold">
                          {product.name}
                        </Typography>
                        <Typography variant="caption" color="textSecondary">
                          {product.product_string}
                        </Typography>
                      </TableCell>
                      <TableCell>{product.description}</TableCell>
                      <TableCell>{product.quantity_ordered}</TableCell>
                      <TableCell>${product.price}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>

            {/* FIXED: Enhanced Timeline Display */}
            <Divider style={{ margin: '16px 0' }} />
            <Typography variant="h6" gutterBottom>Order Timeline</Typography>
            <Box>
              {order?.state_history?.map((state, index) => (
                <Box key={index} style={{
                  padding: '8px 0',
                  borderLeft: index === order.state_history.length - 1 ? '3px solid #4caf50' : '3px solid #e0e0e0',
                  paddingLeft: '16px',
                  marginLeft: '8px'
                }}>
                  <Typography variant="subtitle2" fontWeight="bold">
                    {state.state_name}
                  </Typography>
                  <Typography variant="body2" color="textSecondary">
                    {new Date(state.timestamp).toLocaleString()}
                  </Typography>
                  <Typography variant="caption">
                    {state.user}
                  </Typography>
                </Box>
              ))}
            </Box>
          </Box>
        );

      case 1: // Packing
        return (
          <ProductPackingForm
            products={order?.products || []}
            boxes={boxes}
            onUpdateProducts={handleUpdateProducts}
            onUpdateBoxes={handleUpdateBoxes}
            classes={classes}
          />
        );

      case 2: // Dispatch Ready
        const totalProductsPacked = Object.values(productQuantities).reduce((sum, qty) => sum + qty, 0);
        const totalProductsOrdered = order?.products?.reduce((sum, product) => sum + product.quantity_ordered, 0) || 0;
        const remainingProducts = totalProductsOrdered - totalProductsPacked;

        return (
          <Box>
            <Typography variant="h6" gutterBottom>Dispatch Ready Summary</Typography>

            <Box mb={3} p={2} bgcolor="#e8f5e8" borderRadius={1} border="1px solid #4caf50">
              <Typography variant="body1">
                <strong>Total Products Ordered:</strong> {totalProductsOrdered}
              </Typography>
              <Typography variant="body1">
                <strong>Products Ready for Dispatch:</strong> {totalProductsPacked}
              </Typography>
              {remainingProducts > 0 && (
                <Typography variant="body1" color="warning.main">
                  <strong>Remaining Products:</strong> {remainingProducts}
                </Typography>
              )}
              <Typography variant="body1" style={{ marginTop: 8 }}>
                <strong>Status:</strong> {remainingProducts > 0 ? 'Partially Completed' : 'Dispatch Ready'}
              </Typography>
            </Box>

            <Typography variant="subtitle1" gutterBottom>Final Box Contents:</Typography>
            {boxes.map((box) => {
              const productsInBox = order?.products?.filter(product =>
                productBoxAssignments[product.product_id] &&
                productBoxAssignments[product.product_id].includes(box.box_id) &&
                (boxProductQuantities[product.product_id]?.[box.box_id] || 0) > 0
              ) || [];

              if (productsInBox.length === 0) return null;

              return (
                <Card key={box.box_id} style={{ marginBottom: 8 }}>
                  <CardContent>
                    <Typography variant="subtitle2" gutterBottom>
                      <IconBox size={16} style={{ marginRight: 4 }} />
                      {box.box_name}
                    </Typography>
                    {productsInBox.map((product) => (
                      <Typography key={product.product_id} variant="body2" color="textSecondary">
                        {product.name}: {boxProductQuantities[product.product_id]?.[box.box_id] || 0} units
                      </Typography>
                    ))}
                  </CardContent>
                </Card>
              );
            })}

            {/* Display final order information if available */}
            {order?.final_order && (
              <Box mt={2} p={2} bgcolor="#f5f5f5" borderRadius={1}>
                <Typography variant="subtitle2" gutterBottom>Final Order Information:</Typography>
                <Typography variant="body2">Order Number: {order.final_order.order_number}</Typography>
                <Typography variant="body2">Status: {order.final_order.status}</Typography>
                <Typography variant="body2">Created: {new Date(order.final_order.created_at).toLocaleString()}</Typography>
              </Box>
            )}
          </Box>
        );

      case 3: // FIXED: Completed with remaining products display
        const isPartiallyCompleted = order?.status?.toLowerCase().includes('partially');

        return (
          <Box textAlign="center" p={4}>
            <IconCheck size={64} color={isPartiallyCompleted ? "#ff9800" : "#4caf50"} style={{ marginBottom: 16 }} />
            <Typography variant="h5" gutterBottom>
              Order {isPartiallyCompleted ? 'Partially Completed' : 'Completed'}
            </Typography>
            <Typography variant="body1" color="textSecondary">
              {isPartiallyCompleted
                ? 'This order has been partially completed with some items remaining.'
                : 'This order has been successfully dispatched from the warehouse.'}
            </Typography>

            {/* Show remaining products for partially completed orders */}
            {isPartiallyCompleted && order?.products && (
              <Box mt={3} textAlign="left">
                <Typography variant="h6" gutterBottom>
                  Remaining Products:
                </Typography>
                <TableContainer component={Paper}>
                  <Table size="small">
                    <TableHead>
                      <TableRow>
                        <TableCell>Product</TableCell>
                        <TableCell align="right">Originally Ordered</TableCell>
                        <TableCell align="right">Packed</TableCell>
                        <TableCell align="right">Remaining</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {order.products
                        .filter(product => {
                          const packed = product.quantity_packed || 0;
                          const ordered = product.quantity_ordered || 0;
                          return ordered > packed;
                        })
                        .map((product) => {
                          const packed = product.quantity_packed || 0;
                          const ordered = product.quantity_ordered || 0;
                          const remaining = ordered - packed;

                          return (
                            <TableRow key={product.product_id}>
                              <TableCell>
                                <Typography variant="body2" fontWeight="bold">
                                  {product.name}
                                </Typography>
                                <Typography variant="caption" color="textSecondary">
                                  {product.product_string}
                                </Typography>
                              </TableCell>
                              <TableCell align="right">{ordered}</TableCell>
                              <TableCell align="right">{packed}</TableCell>
                              <TableCell align="right">
                                <Typography color="warning.main" fontWeight="bold">
                                  {remaining}
                                </Typography>
                              </TableCell>
                            </TableRow>
                          );
                        })}
                    </TableBody>
                  </Table>
                </TableContainer>

                {/* Add summary */}
                <Box mt={2} p={2} bgcolor="warning.light" borderRadius={1}>
                  <Typography variant="body2">
                    <strong>Note:</strong> These remaining items can be processed in a new order.
                  </Typography>
                </Box>
              </Box>
            )}

            {order?.final_order?.dispatched_date && (
              <Typography variant="body2" style={{ marginTop: 16 }}>
                Dispatched on: {new Date(order.final_order.dispatched_date).toLocaleString()}
              </Typography>
            )}
          </Box>
        );

      default:
        return null;
    }
  };

  if (!order) return null;

  return (
    <>
      <Dialog
        open={open}
        onClose={onClose}
        maxWidth="lg"
        fullWidth
        className={classes.orderDetailsDialog}
      >
        <DialogTitle>
          <Box display="flex" alignItems="center" justifyContent="space-between">
            <Box display="flex" alignItems="center">
              <IconPackage size={24} style={{ marginRight: 8 }} />
              <Typography variant="h5">Order Management: {order.order_request_id}</Typography>
            </Box>
            <Chip
              label={order.status?.replace('-', ' ') || 'Unknown'}
              color="primary"
              size="small"
            />
          </Box>
        </DialogTitle>

        <DialogContent style={{ minHeight: '500px' }}>
          <Stepper activeStep={activeStep} style={{ marginBottom: 24 }}>
            {steps.map((label) => (
              <Step key={label}>
                <StepLabel>{label}</StepLabel>
              </Step>
            ))}
          </Stepper>

          {renderStepContent()}
        </DialogContent>

        <DialogActions>
          <Button onClick={onClose} disabled={loading}>
            Close
          </Button>

          {/* FIXED: Proper action buttons based on status */}
          {activeStep === 0 && order.status?.toLowerCase() === 'picking' && (
            <Button
              onClick={() => setActiveStep(1)}
              color="primary"
              variant="contained"
              disabled={loading}
            >
              Start Packing
            </Button>
          )}

          {activeStep === 1 && order.status?.toLowerCase() === 'packing' && (
            <Button
              onClick={handleMoveToDispatchReady}
              color="primary"
              variant="contained"
              disabled={loading}
              startIcon={<IconTruck size={16} />}
            >
              {loading ? <CircularProgress size={20} /> : 'Move to Dispatch Ready'}
            </Button>
          )}

          {activeStep === 2 && order.status?.toLowerCase().includes('dispatch') && (
            <Button
              onClick={handleCompleteDispatch}
              color="secondary"
              variant="contained"
              disabled={loading}
              startIcon={<IconCheck size={16} />}
            >
              {loading ? <CircularProgress size={20} /> : 'Complete Dispatch'}
            </Button>
          )}
        </DialogActions>
      </Dialog>
    </>
  );
};