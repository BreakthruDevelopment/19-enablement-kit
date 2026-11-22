/*
 * Harbor OMS. Synthetic order-management code written for this repository.
 */
package com.harbor.oms.product;

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

import com.harbor.oms.dao.ProductDao;
import com.harbor.oms.support.OmsException;

/**
 * A sku stocked in one warehouse. The desk reserves quantity off on_hand.
 */
public class ProductBean implements EntityBean {

    private EntityContext entityContext;

    private String sku;
    private String description;
    private long unitPriceCents;
    private int onHand;
    private String warehouseCode;
    private int reorderPoint;
    private String activeFlag;
    private String vendorCode;

    public String ejbCreate(String sku, String description, long unitPriceCents, int onHand, String warehouseCode, int reorderPoint, String activeFlag, String vendorCode)
            throws CreateException, RemoteException {
        if (sku == null || sku.length() == 0) {
            throw new CreateException("product key is required");
        }
        Connection connection = null;
        try {
            connection = lookupOrderDataSource().getConnection();
            ProductDao.Row row = new ProductDao.Row();
            row.setSku(sku);
            row.setDescription(description);
            row.setUnitPriceCents(unitPriceCents);
            row.setOnHand(onHand);
            row.setWarehouseCode(warehouseCode);
            row.setReorderPoint(reorderPoint);
            row.setActiveFlag(activeFlag);
            row.setVendorCode(vendorCode);
            new ProductDao().insert(connection, row);
            return sku;
        } catch (NamingException failure) {
            throw new EJBException("product datasource lookup failed", failure);
        } catch (SQLException failure) {
            throw new CreateException("product insert failed: " + failure.getMessage());
        } finally {
            close(connection);
        }
    }

    public void ejbPostCreate(String sku, String description, long unitPriceCents, int onHand, String warehouseCode, int reorderPoint, String activeFlag, String vendorCode) throws CreateException, RemoteException {
    }

    public void ejbLoad() throws RemoteException {
        String key = (String) entityContext.getPrimaryKey();
        Connection connection = null;
        try {
            connection = lookupOrderDataSource().getConnection();
            ProductDao.Row row = new ProductDao().findById(connection, key);
            if (row == null) {
                throw new EJBException(
                        "product disappeared during load: " + key);
            }
            copyFrom(row);
        } catch (NamingException failure) {
            throw new EJBException("product datasource lookup failed", failure);
        } catch (SQLException failure) {
            throw new EJBException("product load failed: " + key, failure);
        } finally {
            close(connection);
        }
    }

    public void ejbStore() throws RemoteException {
        Connection connection = null;
        try {
            connection = lookupOrderDataSource().getConnection();
            ProductDao.Row row = new ProductDao.Row();
            copyTo(row);
            new ProductDao().update(connection, row);
        } catch (NamingException failure) {
            throw new EJBException("product datasource lookup failed", failure);
        } catch (SQLException failure) {
            throw new EJBException("product store failed", failure);
        } finally {
            close(connection);
        }
    }

    public void ejbRemove() throws RemoveException, RemoteException {
        String key = (String) entityContext.getPrimaryKey();
        Connection connection = null;
        try {
            connection = lookupOrderDataSource().getConnection();
            int removed = new ProductDao().delete(connection, key);
            if (removed != 1) {
                throw new RemoveException("product was not removed: " + key);
            }
        } catch (NamingException failure) {
            throw new EJBException("product datasource lookup failed", failure);
        } catch (SQLException failure) {
            throw new EJBException("product remove failed: " + key, failure);
        } finally {
            close(connection);
        }
    }

    public String ejbFindByPrimaryKey(String key)
            throws FinderException, RemoteException {
        if (key == null || key.length() == 0) {
            throw new FinderException("product key is required");
        }
        Connection connection = null;
        try {
            connection = lookupOrderDataSource().getConnection();
            ProductDao.Row row = new ProductDao().findById(connection, key);
            if (row == null) {
                throw new FinderException("product not found: " + key);
            }
            return key;
        } catch (NamingException failure) {
            throw new EJBException("product datasource lookup failed", failure);
        } catch (SQLException failure) {
            throw new EJBException("product find failed: " + key, failure);
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

    private void copyFrom(ProductDao.Row row) {
        this.sku = row.getSku();
        this.description = row.getDescription();
        this.unitPriceCents = row.getUnitPriceCents();
        this.onHand = row.getOnHand();
        this.warehouseCode = row.getWarehouseCode();
        this.reorderPoint = row.getReorderPoint();
        this.activeFlag = row.getActiveFlag();
        this.vendorCode = row.getVendorCode();
    }

    private void copyTo(ProductDao.Row row) {
        row.setSku(this.sku);
        row.setDescription(this.description);
        row.setUnitPriceCents(this.unitPriceCents);
        row.setOnHand(this.onHand);
        row.setWarehouseCode(this.warehouseCode);
        row.setReorderPoint(this.reorderPoint);
        row.setActiveFlag(this.activeFlag);
        row.setVendorCode(this.vendorCode);
    }

    /**
     * Return the stored sku.
     */
    public String getSku() {
        return sku;
    }

    /**
     * Return the stored description.
     */
    public String getDescription() {
        return description;
    }

    /**
     * Replace the stored description.
     */
    public void setDescription(String value) {
        this.description = value;
    }

    /**
     * Return the stored unit_price_cents.
     */
    public long getUnitPriceCents() {
        return unitPriceCents;
    }

    /**
     * Replace the stored unit_price_cents.
     */
    public void setUnitPriceCents(long value) {
        this.unitPriceCents = value;
    }

    /**
     * Return the stored on_hand.
     */
    public int getOnHand() {
        return onHand;
    }

    /**
     * Replace the stored on_hand.
     */
    public void setOnHand(int value) {
        this.onHand = value;
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
     * Return the stored reorder_point.
     */
    public int getReorderPoint() {
        return reorderPoint;
    }

    /**
     * Replace the stored reorder_point.
     */
    public void setReorderPoint(int value) {
        this.reorderPoint = value;
    }

    /**
     * Return the stored active_flag.
     */
    public String getActiveFlag() {
        return activeFlag;
    }

    /**
     * Replace the stored active_flag.
     */
    public void setActiveFlag(String value) {
        this.activeFlag = value;
    }

    /**
     * Return the stored vendor_code.
     */
    public String getVendorCode() {
        return vendorCode;
    }

    /**
     * Replace the stored vendor_code.
     */
    public void setVendorCode(String value) {
        this.vendorCode = value;
    }

    public void reserve(int quantity) throws OmsException {
        if (quantity <= 0) {
            throw new OmsException("quantity must be positive");
        }
        if (onHand < quantity) {
            throw new OmsException("not enough on hand for " + sku);
        }
        onHand = onHand - quantity;
    }

    public void release(int quantity) throws OmsException {
        if (quantity <= 0) {
            throw new OmsException("quantity must be positive");
        }
        onHand = onHand + quantity;
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
