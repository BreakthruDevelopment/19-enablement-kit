/*
 * Harbor OMS. Synthetic order-management code written for this repository.
 */
package com.harbor.oms.order;

import java.rmi.RemoteException;
import java.sql.Connection;
import java.sql.SQLException;

import javax.ejb.CreateException;
import javax.ejb.EJBException;
import javax.ejb.EntityBean;
import javax.ejb.EntityContext;
import javax.ejb.FinderException;
import javax.ejb.RemoveException;
import javax.naming.InitialContext;
import javax.naming.NamingException;
import javax.sql.DataSource;

import com.harbor.oms.dao.OrderDao;
import com.harbor.oms.order.OrderLine;
import com.harbor.oms.support.OmsException;

/**
 * One desk order for one sku. The line row is written with the order.
 */
public class SalesOrderBean implements EntityBean {

    private EntityContext entityContext;

    private String orderId;
    private String customerId;
    private String statusCode;
    private String placedOn;
    private String requestedShip;
    private long totalCents;
    private String currencyCode;
    private String buyerPo;
    private String warehouseCode;
    private String lineSku;
    private int lineQuantity;

    public String ejbCreate(String orderId, String customerId, String statusCode, String placedOn, String requestedShip, long totalCents, String currencyCode, String buyerPo, String warehouseCode, String lineSku, int lineQuantity)
            throws CreateException, RemoteException {
        if (orderId == null || orderId.length() == 0) {
            throw new CreateException("sales_order key is required");
        }
        if (lineQuantity <= 0) {
            throw new CreateException("line quantity must be positive");
        }
        Connection connection = null;
        try {
            connection = lookupOrderDataSource().getConnection();
            OrderDao.Row row = new OrderDao.Row();
            row.setOrderId(orderId);
            row.setCustomerId(customerId);
            row.setStatusCode(statusCode);
            row.setPlacedOn(placedOn);
            row.setRequestedShip(requestedShip);
            row.setTotalCents(totalCents);
            row.setCurrencyCode(currencyCode);
            row.setBuyerPo(buyerPo);
            row.setWarehouseCode(warehouseCode);
            row.setLineSku(lineSku);
            row.setLineQuantity(lineQuantity);
            new OrderDao().insert(connection, row);
            long unitPrice = totalCents / lineQuantity;
            OrderLine line = new OrderLine(lineSku, lineQuantity, unitPrice);
            new OrderDao().insertLine(connection, orderId, line);
            return orderId;
        } catch (NamingException failure) {
            throw new EJBException("sales_order datasource lookup failed", failure);
        } catch (SQLException failure) {
            throw new CreateException("sales_order insert failed: " + failure.getMessage());
        } finally {
            close(connection);
        }
    }

    public void ejbPostCreate(String orderId, String customerId, String statusCode, String placedOn, String requestedShip, long totalCents, String currencyCode, String buyerPo, String warehouseCode, String lineSku, int lineQuantity) throws CreateException, RemoteException {
    }

    public void ejbLoad() throws RemoteException {
        String key = (String) entityContext.getPrimaryKey();
        Connection connection = null;
        try {
            connection = lookupOrderDataSource().getConnection();
            OrderDao.Row row = new OrderDao().findById(connection, key);
            if (row == null) {
                throw new EJBException(
                        "sales_order disappeared during load: " + key);
            }
            copyFrom(row);
        } catch (NamingException failure) {
            throw new EJBException("sales_order datasource lookup failed", failure);
        } catch (SQLException failure) {
            throw new EJBException("sales_order load failed: " + key, failure);
        } finally {
            close(connection);
        }
    }

    public void ejbStore() throws RemoteException {
        Connection connection = null;
        try {
            connection = lookupOrderDataSource().getConnection();
            OrderDao.Row row = new OrderDao.Row();
            copyTo(row);
            new OrderDao().update(connection, row);
        } catch (NamingException failure) {
            throw new EJBException("sales_order datasource lookup failed", failure);
        } catch (SQLException failure) {
            throw new EJBException("sales_order store failed", failure);
        } finally {
            close(connection);
        }
    }

    public void ejbRemove() throws RemoveException, RemoteException {
        String key = (String) entityContext.getPrimaryKey();
        Connection connection = null;
        try {
            connection = lookupOrderDataSource().getConnection();
            int removed = new OrderDao().delete(connection, key);
            if (removed != 1) {
                throw new RemoveException("sales_order was not removed: " + key);
            }
        } catch (NamingException failure) {
            throw new EJBException("sales_order datasource lookup failed", failure);
        } catch (SQLException failure) {
            throw new EJBException("sales_order remove failed: " + key, failure);
        } finally {
            close(connection);
        }
    }

    public String ejbFindByPrimaryKey(String key)
            throws FinderException, RemoteException {
        if (key == null || key.length() == 0) {
            throw new FinderException("sales_order key is required");
        }
        Connection connection = null;
        try {
            connection = lookupOrderDataSource().getConnection();
            OrderDao.Row row = new OrderDao().findById(connection, key);
            if (row == null) {
                throw new FinderException("sales_order not found: " + key);
            }
            return key;
        } catch (NamingException failure) {
            throw new EJBException("sales_order datasource lookup failed", failure);
        } catch (SQLException failure) {
            throw new EJBException("sales_order find failed: " + key, failure);
        } finally {
            close(connection);
        }
    }

    public void ejbActivate() throws RemoteException {
    }

    public void ejbPassivate() throws RemoteException {
    }

    public void setEntityContext(EntityContext context) throws RemoteException {
        this.entityContext = context;
    }

    public void unsetEntityContext() throws RemoteException {
        this.entityContext = null;
    }

    private void copyFrom(OrderDao.Row row) {
        this.orderId = row.getOrderId();
        this.customerId = row.getCustomerId();
        this.statusCode = row.getStatusCode();
        this.placedOn = row.getPlacedOn();
        this.requestedShip = row.getRequestedShip();
        this.totalCents = row.getTotalCents();
        this.currencyCode = row.getCurrencyCode();
        this.buyerPo = row.getBuyerPo();
        this.warehouseCode = row.getWarehouseCode();
        this.lineSku = row.getLineSku();
        this.lineQuantity = row.getLineQuantity();
    }

    private void copyTo(OrderDao.Row row) {
        row.setOrderId(this.orderId);
        row.setCustomerId(this.customerId);
        row.setStatusCode(this.statusCode);
        row.setPlacedOn(this.placedOn);
        row.setRequestedShip(this.requestedShip);
        row.setTotalCents(this.totalCents);
        row.setCurrencyCode(this.currencyCode);
        row.setBuyerPo(this.buyerPo);
        row.setWarehouseCode(this.warehouseCode);
        row.setLineSku(this.lineSku);
        row.setLineQuantity(this.lineQuantity);
    }

    /**
     * Return the stored order_id.
     */
    public String getOrderId() {
        return orderId;
    }

    /**
     * Return the stored customer_id.
     */
    public String getCustomerId() {
        return customerId;
    }

    /**
     * Replace the stored customer_id.
     */
    public void setCustomerId(String value) {
        this.customerId = value;
    }

    /**
     * Return the stored status_code.
     */
    public String getStatusCode() {
        return statusCode;
    }

    /**
     * Replace the stored status_code.
     */
    public void setStatusCode(String value) {
        this.statusCode = value;
    }

    /**
     * Return the stored placed_on.
     */
    public String getPlacedOn() {
        return placedOn;
    }

    /**
     * Replace the stored placed_on.
     */
    public void setPlacedOn(String value) {
        this.placedOn = value;
    }

    /**
     * Return the stored requested_ship.
     */
    public String getRequestedShip() {
        return requestedShip;
    }

    /**
     * Replace the stored requested_ship.
     */
    public void setRequestedShip(String value) {
        this.requestedShip = value;
    }

    /**
     * Return the stored total_cents.
     */
    public long getTotalCents() {
        return totalCents;
    }

    /**
     * Replace the stored total_cents.
     */
    public void setTotalCents(long value) {
        this.totalCents = value;
    }

    /**
     * Return the stored currency_code.
     */
    public String getCurrencyCode() {
        return currencyCode;
    }

    /**
     * Replace the stored currency_code.
     */
    public void setCurrencyCode(String value) {
        this.currencyCode = value;
    }

    /**
     * Return the stored buyer_po.
     */
    public String getBuyerPo() {
        return buyerPo;
    }

    /**
     * Replace the stored buyer_po.
     */
    public void setBuyerPo(String value) {
        this.buyerPo = value;
    }

    /**
     * Return the stored warehouse_code.
     */
    public String getWarehouseCode() {
        return warehouseCode;
    }

    /**
     * Replace the stored warehouse_code.
     */
    public void setWarehouseCode(String value) {
        this.warehouseCode = value;
    }

    /**
     * Return the stored line_sku.
     */
    public String getLineSku() {
        return lineSku;
    }

    /**
     * Replace the stored line_sku.
     */
    public void setLineSku(String value) {
        this.lineSku = value;
    }

    /**
     * Return the stored line_quantity.
     */
    public int getLineQuantity() {
        return lineQuantity;
    }

    /**
     * Replace the stored line_quantity.
     */
    public void setLineQuantity(int value) {
        this.lineQuantity = value;
    }

    public void cancel() throws OmsException {
        if (!"OPEN".equals(statusCode) && !"ALLOCATED".equals(statusCode)) {
            throw new OmsException("order cannot be cancelled");
        }
        statusCode = "CANCELLED";
    }

    public void attachBuyerPo(String buyerPo) throws OmsException {
        if (buyerPo == null || buyerPo.length() == 0) {
            throw new OmsException("buyer PO is required");
        }
        if (!"OPEN".equals(statusCode)) {
            throw new OmsException(
                    "buyer PO is frozen once the order leaves the desk");
        }
        this.buyerPo = buyerPo;
    }

    private DataSource lookupOrderDataSource() throws NamingException {
        InitialContext naming = new InitialContext();
        return (DataSource) naming.lookup("java:comp/env/jdbc/OrderDS");
    }

    private void close(Connection connection) {
        if (connection == null) {
            return;
        }
        try {
            connection.close();
        } catch (SQLException failure) {
            throw new EJBException("failed to close a JDBC connection", failure);
        }
    }
}
