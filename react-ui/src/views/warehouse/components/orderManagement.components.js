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
  IconMinus,
  IconChevronDown
} from '@tabler/icons';
import { STATUS_FILTER_OPTIONS, TABLE_COLUMNS } from '../constants/orderManagement.constants';
import { formatDate, getTimeInCurrentStatus, getNextStatus, getStatusChipClass } from '../utils/orderManagement.utils';

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
  const normalizedStatus = String(status).toLowerCase();
  const className = classes[getStatusChipClass(status)];

  return (
    <Chip
      label={normalizedStatus.charAt(0).toUpperCase() + normalizedStatus.slice(1)}
      className={`${classes.statusChip} ${className}`}
      size="small"
    />
  );
};

/**
 * Status Action Button Component
 */
export const StatusActionButton = ({ order, onStatusUpdate, classes }) => {
  const nextStatus = getNextStatus(order.status);

  if (!nextStatus) return null;

  return (
    <Button
      variant="outlined"
      color="primary"
      size="small"
      className={classes.statusActionButton}
      onClick={(e) => {
        e.stopPropagation();
        onStatusUpdate(order, nextStatus);
      }}
      startIcon={<IconArrowRight size={16} />}
    >
      Move to {nextStatus.charAt(0).toUpperCase() + nextStatus.slice(1)}
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
 * Product Packing Component
 */
/**
 * FIXED: Product Packing Component with proper box assignment tracking
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

  const handleBoxQuantityChange = (productId, boxId, quantity) => {
    const newQuantity = parseInt(quantity) || 0;

    const newBoxQuantities = {
      ...boxProductQuantities,
      [productId]: {
        ...boxProductQuantities[productId],
        [boxId]: newQuantity
      }
    };
    setBoxProductQuantities(newBoxQuantities);

    // Calculate total packed quantity for this product
    const totalPacked = Object.values(newBoxQuantities[productId] || {}).reduce((sum, qty) => sum + qty, 0);
    const newQuantities = { ...productQuantities, [productId]: totalPacked };
    setProductQuantities(newQuantities);

    // FIXED: Update box assignments - if product has quantity in any box, it's assigned
    const newAssignments = { ...productBoxAssignments };
    const hasQuantityInAnyBox = Object.values(newBoxQuantities[productId] || {}).some(qty => qty > 0);

    if (hasQuantityInAnyBox) {
      // Find the first box that has this product
      const assignedBoxId = Object.keys(newBoxQuantities[productId] || {}).find(
        boxId => (newBoxQuantities[productId][boxId] || 0) > 0
      );
      newAssignments[productId] = assignedBoxId || '';
    } else {
      newAssignments[productId] = '';
    }

    setProductBoxAssignments(newAssignments);

    // Update parent component with all the data
    onUpdateProducts(newQuantities, newAssignments, newBoxQuantities);
  };

  const addNewBox = () => {
    const newBoxId = `B${Date.now()}`; // Use timestamp to ensure uniqueness
    const newBox = {
      box_id: newBoxId,
      box_name: `Box-${boxList.length + 1}`,
      products: []
    };
    const updatedBoxes = [...boxList, newBox];
    setBoxList(updatedBoxes);

    // Initialize quantities for all products in the new box
    const newBoxQuantities = { ...boxProductQuantities };
    products.forEach(product => {
      if (!newBoxQuantities[product.product_id]) {
        newBoxQuantities[product.product_id] = {};
      }
      newBoxQuantities[product.product_id][newBoxId] = 0;
    });
    setBoxProductQuantities(newBoxQuantities);

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
        const totalPacked = Object.values(newBoxQuantities[product.product_id] || {}).reduce((sum, qty) => sum + qty, 0);
        newQuantities[product.product_id] = totalPacked;

        // Update assignment
        const hasQuantityInAnyBox = Object.values(newBoxQuantities[product.product_id] || {}).some(qty => qty > 0);
        if (hasQuantityInAnyBox) {
          const assignedBoxId = Object.keys(newBoxQuantities[product.product_id] || {}).find(
            boxId => (newBoxQuantities[product.product_id][boxId] || 0) > 0
          );
          newAssignments[product.product_id] = assignedBoxId || '';
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
    return Object.values(boxProductQuantities[productId] || {}).reduce((sum, qty) => sum + qty, 0);
  };

  const getBoxTotalQuantity = (boxId) => {
    return products.reduce((total, product) => {
      return total + (boxProductQuantities[product.product_id]?.[boxId] || 0);
    }, 0);
  };

  // FIXED: Better validation function
  const getValidationStatus = () => {
    const errors = [];
    const warnings = [];

    products.forEach(product => {
      const totalInBoxes = getProductTotalInBoxes(product.product_id);
      const hasAssignment = productBoxAssignments[product.product_id];

      if (totalInBoxes > 0 && !hasAssignment) {
        errors.push(`${product.name} has quantity but no box assignment`);
      }

      if (totalInBoxes > product.quantity_available) {
        errors.push(`${product.name} exceeds available quantity`);
      }

      if (totalInBoxes < product.quantity_ordered && totalInBoxes > 0) {
        warnings.push(`${product.name} is partially packed`);
      }
    });

    return { errors, warnings, isValid: errors.length === 0 };
  };

  const validationStatus = getValidationStatus();

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
              <TableCell>Box Assignment</TableCell>
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
                    <Typography variant="body2" color="textSecondary">
                      {hasAssignment ? `Box assigned` : 'No assignment'}
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

      {/* Validation Messages */}
      {(validationStatus.errors.length > 0 || validationStatus.warnings.length > 0) && (
        <Box mb={2} p={2} border="1px solid #e0e0e0" borderRadius={1}>
          {validationStatus.errors.length > 0 && (
            <Box mb={1}>
              <Typography variant="subtitle2" color="error" gutterBottom>
                Errors:
              </Typography>
              {validationStatus.errors.map((error, index) => (
                <Typography key={index} variant="body2" color="error">
                  • {error}
                </Typography>
              ))}
            </Box>
          )}

          {validationStatus.warnings.length > 0 && (
            <Box>
              <Typography variant="subtitle2" style={{ color: '#ff9800' }} gutterBottom>
                Warnings:
              </Typography>
              {validationStatus.warnings.map((warning, index) => (
                <Typography key={index} variant="body2" style={{ color: '#ff9800' }}>
                  • {warning}
                </Typography>
              ))}
            </Box>
          )}
        </Box>
      )}

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

      {/* Enhanced Boxes List with Quantity Division */}
      {boxList.map((box) => {
        const boxTotal = getBoxTotalQuantity(box.box_id);
        const productsInBox = products.filter(product =>
          (boxProductQuantities[product.product_id]?.[box.box_id] || 0) > 0
        );

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
                  const remainingForProduct = product.quantity_available - totalInAllBoxes + currentQuantity;

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
                          onChange={(e) => handleBoxQuantityChange(product.product_id, box.box_id, e.target.value)}
                          inputProps={{
                            min: 0,
                            max: remainingForProduct,
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

      {/* Final Validation Summary */}
      <Box mt={2} p={2} bgcolor={validationStatus.isValid ? '#e8f5e8' : '#ffeaea'} borderRadius={1}>
        <Typography variant="subtitle2" gutterBottom>
          Packing Summary: {validationStatus.isValid ? '✅ Ready for Dispatch' : '❌ Issues Found'}
        </Typography>
        {products.map((product) => {
          const totalInBoxes = getProductTotalInBoxes(product.product_id);
          const hasAssignment = productBoxAssignments[product.product_id];
          const isValid = totalInBoxes <= product.quantity_available && (totalInBoxes === 0 || hasAssignment);

          return (
            <Typography
              key={product.product_id}
              variant="body2"
              color={isValid ? "textPrimary" : "error"}
              style={{ marginBottom: 4 }}
            >
              {product.name}: {totalInBoxes}/{product.quantity_available} packed
              {totalInBoxes > 0 && hasAssignment && ' ✅'}
              {totalInBoxes > 0 && !hasAssignment && ' ❌ No box assignment'}
              {totalInBoxes > product.quantity_available && ' ❌ Exceeds available'}
            </Typography>
          );
        })}
      </Box>
    </Box>
  );
};

/**
 * Enhanced Order Details Dialog Component
 */
/**
 * FIXED: Enhanced Order Details Dialog Component - No restricted globals
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

  const steps = ['Order Details', 'Packing', 'Dispatch'];

  useEffect(() => {
    if (order && order.products) {
      // Initialize with existing data
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

      // Set active step based on order status
      if (order.status === 'packing') {
        setActiveStep(1);
      } else if (order.status === 'dispatch') {
        setActiveStep(2);
      } else {
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

  const handleNext = () => {
    setActiveStep((prevStep) => prevStep + 1);
  };

  const handleBack = () => {
    setActiveStep((prevStep) => prevStep - 1);
  };

  // FIXED: Improved validation logic
  const validatePackingData = () => {
    const errors = [];
    const warnings = [];

    if (!order || !order.products) {
      errors.push('No products found in order');
      return { isValid: false, errors, warnings };
    }

    order.products.forEach(product => {
      const quantity = productQuantities[product.product_id] || 0;
      const boxAssignment = productBoxAssignments[product.product_id];

      // Check if product has quantity but no box assignment
      if (quantity > 0 && !boxAssignment) {
        errors.push(`${product.name} has packed quantity (${quantity}) but no box assignment`);
      }

      // Check if quantity exceeds available
      if (quantity > product.quantity_available) {
        errors.push(`${product.name} packed quantity (${quantity}) exceeds available quantity (${product.quantity_available})`);
      }

      // Warning for partial packing
      if (quantity > 0 && quantity < product.quantity_ordered) {
        warnings.push(`${product.name} is partially packed (${quantity}/${product.quantity_ordered})`);
      }
    });

    // Check that at least one product has quantity
    const totalPacked = Object.values(productQuantities).reduce((sum, qty) => sum + (qty || 0), 0);
    if (totalPacked === 0) {
      errors.push('No products have been packed. Please pack at least one product.');
    }

    // Check that all boxes have at least one product
    boxes.forEach(box => {
      const hasProducts = order.products.some(product =>
        productBoxAssignments[product.product_id] === box.box_id &&
        (productQuantities[product.product_id] || 0) > 0
      );

      if (!hasProducts) {
        warnings.push(`${box.box_name} has no products assigned`);
      }
    });

    return {
      isValid: errors.length === 0,
      errors,
      warnings
    };
  };

  const proceedWithPacking = async () => {
    setShowWarningDialog(false);
    await continuePacking();
  };

  const continuePacking = async () => {
    setLoading(true);
    try {
      // Create proper product data with box assignments
      const productsData = order.products.map(product => ({
        product_id: product.product_id,
        quantity_packed: productQuantities[product.product_id] || 0,
        box_assignment: productBoxAssignments[product.product_id] || null
      }));

      // Create proper box data with product assignments
      const boxesData = boxes.map(box => ({
        box_id: box.box_id,
        box_name: box.box_name,
        products: order.products
          .filter(product => productBoxAssignments[product.product_id] === box.box_id)
          .map(product => ({
            product_id: product.product_id,
            quantity: productQuantities[product.product_id] || 0
          }))
          .filter(p => p.quantity > 0)
      })).filter(box => box.products.length > 0);

      // Update order to dispatch status
      await onStatusUpdate(order, 'dispatch', {
        products: productsData,
        boxes: boxesData
      });

      handleNext();
    } catch (error) {
      console.error('Error completing packing:', error);
      alert('Error completing packing: ' + error.message);
    } finally {
      setLoading(false);
    }
  };

  const handlePackingComplete = async () => {
    // Validate before proceeding
    const validation = validatePackingData();

    if (!validation.isValid) {
      alert('Please fix the following errors before proceeding:\n\n' + validation.errors.join('\n'));
      return;
    }

    // Show warnings if any
    if (validation.warnings.length > 0) {
      setWarningMessages(validation.warnings);
      setShowWarningDialog(true);
      return;
    }

    await continuePacking();
  };

  const handleFinalDispatch = async () => {
    setLoading(true);
    try {
      // Create final order data
      const productsData = order.products.map(product => ({
        product_id: product.product_id,
        quantity_packed: productQuantities[product.product_id] || 0
      })).filter(p => p.quantity_packed > 0);

      const boxesData = boxes.map(box => ({
        box_name: box.box_name,
        products: order.products
          .filter(product => productBoxAssignments[product.product_id] === box.box_id)
          .map(product => ({
            product_id: product.product_id,
            quantity: productQuantities[product.product_id] || 0
          }))
          .filter(p => p.quantity > 0)
      })).filter(box => box.products.length > 0);

      const response = await fetch(`/api/orders/${order.order_request_id}/dispatch`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          products: productsData,
          boxes: boxesData
        })
      });

      const result = await response.json();

      if (result.success) {
        const message = [
          `Order dispatched successfully!`,
          `Order Number: ${result.final_order_id}`,
          `Products Dispatched: ${result.products_dispatched}`
        ];

        if (result.remaining_products > 0) {
          message.push(`Remaining Products: ${result.remaining_products}`);
        }

        alert(message.join('\n'));
        onClose();
      } else {
        throw new Error(result.msg);
      }
    } catch (error) {
      console.error('Error dispatching order:', error);
      alert('Error dispatching order: ' + error.message);
    } finally {
      setLoading(false);
    }
  };

  const renderStepContent = () => {
    switch (activeStep) {
      case 0:
        return (
          <Box>
            <Grid container spacing={2}>
              <Grid item xs={12} md={6}>
                <Typography variant="subtitle2" gutterBottom>Order ID:</Typography>
                <Typography variant="body1" gutterBottom>{order?.order_request_id}</Typography>
              </Grid>
              <Grid item xs={12} md={6}>
                <Typography variant="subtitle2" gutterBottom>Original Order ID:</Typography>
                <Typography variant="body1" gutterBottom>{order?.original_order_id}</Typography>
              </Grid>
              <Grid item xs={12} md={6}>
                <Typography variant="subtitle2" gutterBottom>Dealer:</Typography>
                <Typography variant="body1" gutterBottom>{order?.dealer_name}</Typography>
              </Grid>
              <Grid item xs={12} md={6}>
                <Typography variant="subtitle2" gutterBottom>Status:</Typography>
                <StatusChip status={order?.status} classes={classes} />
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
          </Box>
        );

      case 1:
        return (
          <ProductPackingForm
            products={order?.products || []}
            boxes={boxes}
            onUpdateProducts={handleUpdateProducts}
            onUpdateBoxes={handleUpdateBoxes}
            classes={classes}
          />
        );

      case 2:
        const totalProductsPacked = Object.values(productQuantities).reduce((sum, qty) => sum + qty, 0);
        const totalProductsOrdered = order?.products?.reduce((sum, product) => sum + product.quantity_ordered, 0) || 0;

        return (
          <Box>
            <Typography variant="h6" gutterBottom>Dispatch Summary</Typography>

            <Box mb={3} p={2} bgcolor="background.paper" borderRadius={1} border="1px solid #e0e0e0">
              <Typography variant="body1">
                <strong>Total Products Ordered:</strong> {totalProductsOrdered}
              </Typography>
              <Typography variant="body1">
                <strong>Total Products Packed:</strong> {totalProductsPacked}
              </Typography>
              <Typography variant="body1">
                <strong>Remaining Products:</strong> {totalProductsOrdered - totalProductsPacked}
              </Typography>
            </Box>

            <Typography variant="subtitle1" gutterBottom>Final Box Contents:</Typography>
            {boxes.map((box) => {
              const productsInBox = order?.products?.filter(product =>
                productBoxAssignments[product.product_id] === box.box_id &&
                (productQuantities[product.product_id] || 0) > 0
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
                        {product.name}: {productQuantities[product.product_id] || 0} units
                      </Typography>
                    ))}
                  </CardContent>
                </Card>
              );
            })}
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
            <StatusChip status={order.status} classes={classes} />
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

          {activeStep > 0 && (
            <Button onClick={handleBack} disabled={loading}>
              Back
            </Button>
          )}

          {activeStep === 0 && order.status === 'picking' && (
            <Button
              onClick={handleNext}
              color="primary"
              variant="contained"
              disabled={loading}
            >
              Start Packing
            </Button>
          )}

          {activeStep === 1 && (
            <Button
              onClick={handlePackingComplete}
              color="primary"
              variant="contained"
              disabled={loading}
            >
              {loading ? <CircularProgress size={20} /> : 'Complete Packing'}
            </Button>
          )}

          {activeStep === 2 && (
            <Button
              onClick={handleFinalDispatch}
              color="secondary"
              variant="contained"
              disabled={loading}
            >
              {loading ? <CircularProgress size={20} /> : 'Final Dispatch'}
            </Button>
          )}
        </DialogActions>
      </Dialog>

      {/* Warning Dialog */}
      <Dialog open={showWarningDialog} onClose={() => setShowWarningDialog(false)}>
        <DialogTitle>Warnings Found</DialogTitle>
        <DialogContent>
          <Typography variant="body1" gutterBottom>
            The following warnings were found:
          </Typography>
          <ul>
            {warningMessages.map((warning, index) => (
              <li key={index}>
                <Typography variant="body2">{warning}</Typography>
              </li>
            ))}
          </ul>
          <Typography variant="body1" style={{ marginTop: 16 }}>
            Do you want to proceed anyway?
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setShowWarningDialog(false)}>
            Cancel
          </Button>
          <Button onClick={proceedWithPacking} color="primary" variant="contained">
            Proceed
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
};