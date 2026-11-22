/*
 * Harbor OMS. Synthetic order-management code written for this repository.
 */
package com.harbor.oms.shipment;

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

import com.harbor.oms.dao.ShipmentDao;
import com.harbor.oms.support.OmsException;

/**
 * A dock shipment against one order, from staged through delivered.
 */
public class ShipmentBean implements EntityBean {

    private EntityContext entityContext;

    private String shipmentId;
    private String orderId;
    private String carrier;
    private String trackingNo;
    private String shippedOn;
    private String statusCode;
    private int weightGrams;
    private String dockDoor;

    public String ejbCreate(String shipmentId, String orderId, String carrier, String trackingNo, String shippedOn, String statusCode, int weightGrams, String dockDoor)
            throws CreateException, RemoteException {
        if (shipmentId == null || shipmentId.length() == 0) {
            throw new CreateException("shipment key is required");
        }
        Connection connection = null;
        try {
            connection = lookupOrderDataSource().getConnection();
            ShipmentDao.Row row = new ShipmentDao.Row();
            row.setShipmentId(shipmentId);
            row.setOrderId(orderId);
            row.setCarrier(carrier);
            row.setTrackingNo(trackingNo);
            row.setShippedOn(shippedOn);
            row.setStatusCode(statusCode);
            row.setWeightGrams(weightGrams);
            row.setDockDoor(dockDoor);
            new ShipmentDao().insert(connection, row);
            return shipmentId;
        } catch (NamingException failure) {
            throw new EJBException("shipment datasource lookup failed", failure);
        } catch (SQLException failure) {
            throw new CreateException("shipment insert failed: " + failure.getMessage());
        } finally {
            close(connection);
        }
    }

    public void ejbPostCreate(String shipmentId, String orderId, String carrier, String trackingNo, String shippedOn, String statusCode, int weightGrams, String dockDoor) throws CreateException, RemoteException {
    }

    public void ejbLoad() throws RemoteException {
        String key = (String) entityContext.getPrimaryKey();
        Connection connection = null;
        try {
            connection = lookupOrderDataSource().getConnection();
            ShipmentDao.Row row = new ShipmentDao().findById(connection, key);
            if (row == null) {
                throw new EJBException(
                        "shipment disappeared during load: " + key);
            }
            copyFrom(row);
        } catch (NamingException failure) {
            throw new EJBException("shipment datasource lookup failed", failure);
        } catch (SQLException failure) {
            throw new EJBException("shipment load failed: " + key, failure);
        } finally {
            close(connection);
        }
    }

    public void ejbStore() throws RemoteException {
        Connection connection = null;
        try {
            connection = lookupOrderDataSource().getConnection();
            ShipmentDao.Row row = new ShipmentDao.Row();
            copyTo(row);
            new ShipmentDao().update(connection, row);
        } catch (NamingException failure) {
            throw new EJBException("shipment datasource lookup failed", failure);
        } catch (SQLException failure) {
            throw new EJBException("shipment store failed", failure);
        } finally {
            close(connection);
        }
    }

    public void ejbRemove() throws RemoveException, RemoteException {
        String key = (String) entityContext.getPrimaryKey();
        Connection connection = null;
        try {
            connection = lookupOrderDataSource().getConnection();
            int removed = new ShipmentDao().delete(connection, key);
            if (removed != 1) {
                throw new RemoveException("shipment was not removed: " + key);
            }
        } catch (NamingException failure) {
            throw new EJBException("shipment datasource lookup failed", failure);
        } catch (SQLException failure) {
            throw new EJBException("shipment remove failed: " + key, failure);
        } finally {
            close(connection);
        }
    }

    public String ejbFindByPrimaryKey(String key)
            throws FinderException, RemoteException {
        if (key == null || key.length() == 0) {
            throw new FinderException("shipment key is required");
        }
        Connection connection = null;
        try {
            connection = lookupOrderDataSource().getConnection();
            ShipmentDao.Row row = new ShipmentDao().findById(connection, key);
            if (row == null) {
                throw new FinderException("shipment not found: " + key);
            }
            return key;
        } catch (NamingException failure) {
            throw new EJBException("shipment datasource lookup failed", failure);
        } catch (SQLException failure) {
            throw new EJBException("shipment find failed: " + key, failure);
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

    private void copyFrom(ShipmentDao.Row row) {
        this.shipmentId = row.getShipmentId();
        this.orderId = row.getOrderId();
        this.carrier = row.getCarrier();
        this.trackingNo = row.getTrackingNo();
        this.shippedOn = row.getShippedOn();
        this.statusCode = row.getStatusCode();
        this.weightGrams = row.getWeightGrams();
        this.dockDoor = row.getDockDoor();
    }

    private void copyTo(ShipmentDao.Row row) {
        row.setShipmentId(this.shipmentId);
        row.setOrderId(this.orderId);
        row.setCarrier(this.carrier);
        row.setTrackingNo(this.trackingNo);
        row.setShippedOn(this.shippedOn);
        row.setStatusCode(this.statusCode);
        row.setWeightGrams(this.weightGrams);
        row.setDockDoor(this.dockDoor);
    }

    /**
     * Return the stored shipment_id.
     */
    public String getShipmentId() {
        return shipmentId;
    }

    /**
     * Return the stored order_id.
     */
    public String getOrderId() {
        return orderId;
    }

    /**
     * Replace the stored order_id.
     */
    public void setOrderId(String value) {
        this.orderId = value;
    }

    /**
     * Return the stored carrier.
     */
    public String getCarrier() {
        return carrier;
    }

    /**
     * Replace the stored carrier.
     */
    public void setCarrier(String value) {
        this.carrier = value;
    }

    /**
     * Return the stored tracking_no.
     */
    public String getTrackingNo() {
        return trackingNo;
    }

    /**
     * Replace the stored tracking_no.
     */
    public void setTrackingNo(String value) {
        this.trackingNo = value;
    }

    /**
     * Return the stored shipped_on.
     */
    public String getShippedOn() {
        return shippedOn;
    }

    /**
     * Replace the stored shipped_on.
     */
    public void setShippedOn(String value) {
        this.shippedOn = value;
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
     * Return the stored weight_grams.
     */
    public int getWeightGrams() {
        return weightGrams;
    }

    /**
     * Replace the stored weight_grams.
     */
    public void setWeightGrams(int value) {
        this.weightGrams = value;
    }

    /**
     * Return the stored dock_door.
     */
    public String getDockDoor() {
        return dockDoor;
    }

    /**
     * Replace the stored dock_door.
     */
    public void setDockDoor(String value) {
        this.dockDoor = value;
    }

    public void markShipped(String trackingNo) throws OmsException {
        if (trackingNo == null || trackingNo.length() == 0) {
            throw new OmsException("tracking number is required");
        }
        if (!"STAGED".equals(statusCode)) {
            throw new OmsException("shipment is not staged");
        }
        this.trackingNo = trackingNo;
        statusCode = "SHIPPED";
    }

    public void markDelivered() throws OmsException {
        if (!"SHIPPED".equals(statusCode)) {
            throw new OmsException("shipment has not left the dock");
        }
        statusCode = "DELIVERED";
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
