/*
 * Harbor OMS. Synthetic order-management code written for this repository.
 */
package com.harbor.oms.customer;

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

import com.harbor.oms.dao.CustomerDao;
import com.harbor.oms.support.OmsException;

/**
 * A buyer the order desk can sell to. Credit and hold status live on this row.
 */
public class CustomerBean implements EntityBean {

    private EntityContext entityContext;

    private String customerId;
    private String legalName;
    private String regionCode;
    private long creditLimitCents;
    private String statusCode;
    private String buyerName;
    private String city;
    private String openedOn;

    public String ejbCreate(String customerId, String legalName, String regionCode, long creditLimitCents, String statusCode, String buyerName, String city, String openedOn)
            throws CreateException, RemoteException {
        if (customerId == null || customerId.length() == 0) {
            throw new CreateException("customer key is required");
        }
        Connection connection = null;
        try {
            connection = lookupOrderDataSource().getConnection();
            CustomerDao.Row row = new CustomerDao.Row();
            row.setCustomerId(customerId);
            row.setLegalName(legalName);
            row.setRegionCode(regionCode);
            row.setCreditLimitCents(creditLimitCents);
            row.setStatusCode(statusCode);
            row.setBuyerName(buyerName);
            row.setCity(city);
            row.setOpenedOn(openedOn);
            new CustomerDao().insert(connection, row);
            return customerId;
        } catch (NamingException failure) {
            throw new EJBException("customer datasource lookup failed", failure);
        } catch (SQLException failure) {
            throw new CreateException("customer insert failed: " + failure.getMessage());
        } finally {
            close(connection);
        }
    }

    public void ejbPostCreate(String customerId, String legalName, String regionCode, long creditLimitCents, String statusCode, String buyerName, String city, String openedOn) throws CreateException, RemoteException {
    }

    public void ejbLoad() throws RemoteException {
        String key = (String) entityContext.getPrimaryKey();
        Connection connection = null;
        try {
            connection = lookupOrderDataSource().getConnection();
            CustomerDao.Row row = new CustomerDao().findById(connection, key);
            if (row == null) {
                throw new EJBException(
                        "customer disappeared during load: " + key);
            }
            copyFrom(row);
        } catch (NamingException failure) {
            throw new EJBException("customer datasource lookup failed", failure);
        } catch (SQLException failure) {
            throw new EJBException("customer load failed: " + key, failure);
        } finally {
            close(connection);
        }
    }

    public void ejbStore() throws RemoteException {
        Connection connection = null;
        try {
            connection = lookupOrderDataSource().getConnection();
            CustomerDao.Row row = new CustomerDao.Row();
            copyTo(row);
            new CustomerDao().update(connection, row);
        } catch (NamingException failure) {
            throw new EJBException("customer datasource lookup failed", failure);
        } catch (SQLException failure) {
            throw new EJBException("customer store failed", failure);
        } finally {
            close(connection);
        }
    }

    public void ejbRemove() throws RemoveException, RemoteException {
        String key = (String) entityContext.getPrimaryKey();
        Connection connection = null;
        try {
            connection = lookupOrderDataSource().getConnection();
            int removed = new CustomerDao().delete(connection, key);
            if (removed != 1) {
                throw new RemoveException("customer was not removed: " + key);
            }
        } catch (NamingException failure) {
            throw new EJBException("customer datasource lookup failed", failure);
        } catch (SQLException failure) {
            throw new EJBException("customer remove failed: " + key, failure);
        } finally {
            close(connection);
        }
    }

    public String ejbFindByPrimaryKey(String key)
            throws FinderException, RemoteException {
        if (key == null || key.length() == 0) {
            throw new FinderException("customer key is required");
        }
        Connection connection = null;
        try {
            connection = lookupOrderDataSource().getConnection();
            CustomerDao.Row row = new CustomerDao().findById(connection, key);
            if (row == null) {
                throw new FinderException("customer not found: " + key);
            }
            return key;
        } catch (NamingException failure) {
            throw new EJBException("customer datasource lookup failed", failure);
        } catch (SQLException failure) {
            throw new EJBException("customer find failed: " + key, failure);
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

    private void copyFrom(CustomerDao.Row row) {
        this.customerId = row.getCustomerId();
        this.legalName = row.getLegalName();
        this.regionCode = row.getRegionCode();
        this.creditLimitCents = row.getCreditLimitCents();
        this.statusCode = row.getStatusCode();
        this.buyerName = row.getBuyerName();
        this.city = row.getCity();
        this.openedOn = row.getOpenedOn();
    }

    private void copyTo(CustomerDao.Row row) {
        row.setCustomerId(this.customerId);
        row.setLegalName(this.legalName);
        row.setRegionCode(this.regionCode);
        row.setCreditLimitCents(this.creditLimitCents);
        row.setStatusCode(this.statusCode);
        row.setBuyerName(this.buyerName);
        row.setCity(this.city);
        row.setOpenedOn(this.openedOn);
    }

    /**
     * Return the stored customer_id.
     */
    public String getCustomerId() {
        return customerId;
    }

    /**
     * Return the stored legal_name.
     */
    public String getLegalName() {
        return legalName;
    }

    /**
     * Replace the stored legal_name.
     */
    public void setLegalName(String value) {
        this.legalName = value;
    }

    /**
     * Return the stored region_code.
     */
    public String getRegionCode() {
        return regionCode;
    }

    /**
     * Replace the stored region_code.
     */
    public void setRegionCode(String value) {
        this.regionCode = value;
    }

    /**
     * Return the stored credit_limit_cents.
     */
    public long getCreditLimitCents() {
        return creditLimitCents;
    }

    /**
     * Replace the stored credit_limit_cents.
     */
    public void setCreditLimitCents(long value) {
        this.creditLimitCents = value;
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
     * Return the stored buyer_name.
     */
    public String getBuyerName() {
        return buyerName;
    }

    /**
     * Replace the stored buyer_name.
     */
    public void setBuyerName(String value) {
        this.buyerName = value;
    }

    /**
     * Return the stored city.
     */
    public String getCity() {
        return city;
    }

    /**
     * Replace the stored city.
     */
    public void setCity(String value) {
        this.city = value;
    }

    /**
     * Return the stored opened_on.
     */
    public String getOpenedOn() {
        return openedOn;
    }

    /**
     * Replace the stored opened_on.
     */
    public void setOpenedOn(String value) {
        this.openedOn = value;
    }

    public void placeOnHold(String reason) throws OmsException {
        if (reason == null || reason.length() == 0) {
            throw new OmsException("a hold reason is required");
        }
        if ("CLOSED".equals(statusCode)) {
            throw new OmsException("closed customers stay closed");
        }
        statusCode = "HOLD";
    }

    public void releaseHold() throws OmsException {
        if (!"HOLD".equals(statusCode)) {
            throw new OmsException("customer is not on hold");
        }
        statusCode = "ACTIVE";
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
