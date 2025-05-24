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
const ProductPackingForm = ({ products, boxes, onUpdateProducts, onUpdateBoxes, classes }) => {
  const [productQuantities, setProductQuantities] = useState({});
  const [productBoxAssignments, setProductBoxAssignments] = useState({});
  const [boxList, setBoxList] = useState(boxes || []);

  useEffect(() => {
    // Initialize quantities and box assignments
    const initialQuantities = {};
    const initialAssignments = {};

    products.forEach(product => {
      initialQuantities[product.product_id] = product.quantity_packed || 0;
      initialAssignments[product.product_id] = product.assigned_to_box || '';
    });

    setProductQuantities(initialQuantities);
    setProductBoxAssignments(initialAssignments);
  }, [products]);

  const handleQuantityChange = (productId, quantity) => {
    const newQuantities = { ...productQuantities, [productId]: parseInt(quantity) || 0 };
    setProductQuantities(newQuantities);
    onUpdateProducts(newQuantities, productBoxAssignments);
  };

  const handleBoxAssignment = (productId, boxId) => {
    const newAssignments = { ...productBoxAssignments, [productId]: boxId };
    setProductBoxAssignments(newAssignments);
    onUpdateProducts(productQuantities, newAssignments);
  };

  const addNewBox = () => {
    const newBoxId = `B${boxList.length + 1}`;
    const newBox = {
      box_id: newBoxId,
      box_name: `Box-${boxList.length + 1}`,
      products: []
    };
    const updatedBoxes = [...boxList, newBox];
    setBoxList(updatedBoxes);
    onUpdateBoxes(updatedBoxes);
  };

  const removeBox = (boxId) => {
    const updatedBoxes = boxList.filter(box => box.box_id !== boxId);
    setBoxList(updatedBoxes);

    // Remove assignments to this box
    const updatedAssignments = { ...productBoxAssignments };
    Object.keys(updatedAssignments).forEach(productId => {
      if (updatedAssignments[productId] === boxId) {
        updatedAssignments[productId] = '';
      }
    });
    setProductBoxAssignments(updatedAssignments);
    onUpdateProducts(productQuantities, updatedAssignments);
    onUpdateBoxes(updatedBoxes);
  };

  return (
    <Box>
      <Typography variant="h6" gutterBottom>
        Product Packing Details
      </Typography>

      {/* Products List */}
      <TableContainer component={Paper} style={{ marginBottom: 16 }}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Product</TableCell>
              <TableCell>Ordered Qty</TableCell>
              <TableCell>Available Qty</TableCell>
              <TableCell>Pack Qty</TableCell>
              <TableCell>Assign to Box</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {products.map((product) => (
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
                  <TextField
                    type="number"
                    size="small"
                    value={productQuantities[product.product_id] || 0}
                    onChange={(e) => handleQuantityChange(product.product_id, e.target.value)}
                    inputProps={{
                      min: 0,
                      max: product.quantity_available,
                      style: { width: '80px' }
                    }}
                  />
                </TableCell>
                <TableCell>
                  <FormControl size="small" style={{ minWidth: 120 }}>
                    <Select
                      value={productBoxAssignments[product.product_id] || ''}
                      onChange={(e) => handleBoxAssignment(product.product_id, e.target.value)}
                      displayEmpty
                    >
                      <MenuItem value="">
                        <em>Select Box</em>
                      </MenuItem>
                      {boxList.map((box) => (
                        <MenuItem key={box.box_id} value={box.box_id}>
                          {box.box_name}
                        </MenuItem>
                      ))}
                    </Select>
                  </FormControl>
                </TableCell>
              </TableRow>
            ))}
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

      {/* Boxes List */}
      {boxList.map((box) => {
        const productsInBox = products.filter(product =>
          productBoxAssignments[product.product_id] === box.box_id
        );

        return (
          <Accordion key={box.box_id} style={{ marginBottom: 8 }}>
            <AccordionSummary expandIcon={<IconChevronDown />}>
              <Box display="flex" alignItems="center" justifyContent="space-between" width="100%">
                <Box display="flex" alignItems="center">
                  <IconBox size={20} style={{ marginRight: 8 }} />
                  <Typography variant="subtitle1">
                    {box.box_name} ({productsInBox.length} products)
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
              {productsInBox.length === 0 ? (
                <Typography color="textSecondary">No products assigned to this box</Typography>
              ) : (
                <List dense>
                  {productsInBox.map((product) => (
                    <ListItem key={product.product_id}>
                      <ListItemText
                        primary={product.name}
                        secondary={`Quantity: ${productQuantities[product.product_id] || 0}`}
                      />
                    </ListItem>
                  ))}
                </List>
              )}
            </AccordionDetails>
          </Accordion>
        );
      })}
    </Box>
  );
};

/**
 * Enhanced Order Details Dialog Component
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
  const [boxes, setBoxes] = useState([]);
  const [loading, setLoading] = useState(false);

  const steps = ['Order Details', 'Packing', 'Dispatch'];

  useEffect(() => {
    if (order && order.products) {
      // Initialize with existing data
      const quantities = {};
      const assignments = {};

      order.products.forEach(product => {
        quantities[product.product_id] = product.quantity_packed || 0;
        assignments[product.product_id] = product.assigned_to_box || '';
      });

      setProductQuantities(quantities);
      setProductBoxAssignments(assignments);
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

  const handleUpdateProducts = (quantities, assignments) => {
    setProductQuantities(quantities);
    setProductBoxAssignments(assignments);
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

  const handlePackingComplete = async () => {
    setLoading(true);
    try {
      // Validate that all products have quantities and box assignments
      let isValid = true;
      const errors = [];

      order.products.forEach(product => {
        const quantity = productQuantities[product.product_id] || 0;
        const boxAssignment = productBoxAssignments[product.product_id];

        if (quantity > 0 && !boxAssignment) {
          errors.push(`${product.name} has quantity but no box assignment`);
          isValid = false;
        }

        if (quantity > product.quantity_available) {
          errors.push(`${product.name} pack quantity exceeds available quantity`);
          isValid = false;
        }
      });

      if (!isValid) {
        alert('Please fix the following errors:\n' + errors.join('\n'));
        return;
      }

      // Update order to dispatch status
      await onStatusUpdate(order, 'dispatch', {
        products: order.products.map(product => ({
          product_id: product.product_id,
          quantity_packed: productQuantities[product.product_id] || 0,
          box_assignment: productBoxAssignments[product.product_id]
        })),
        boxes: boxes
      });

      handleNext();
    } catch (error) {
      console.error('Error completing packing:', error);
      alert('Error completing packing: ' + error.message);
    } finally {
      setLoading(false);
    }
  };

  const handleFinalDispatch = async () => {
    setLoading(true);
    try {
      // Create final order
      const response = await fetch(`/api/orders/${order.order_request_id}/dispatch`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          products: order.products.map(product => ({
            product_id: product.product_id,
            quantity_packed: productQuantities[product.product_id] || 0
          })),
          boxes: boxes
        })
      });

      const result = await response.json();

      if (result.success) {
        alert(`Order dispatched successfully!\nOrder Number: ${result.final_order_id}\nProducts Dispatched: ${result.products_dispatched}`);
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
                productBoxAssignments[product.product_id] === box.box_id
              ) || [];

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
  );
};