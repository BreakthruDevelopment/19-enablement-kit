/*
 * Harbor OMS. Synthetic order-management code written for this repository.
 */
package com.harbor.oms.pricing;

import java.rmi.RemoteException;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.SQLException;

import javax.ejb.EJBException;
import javax.ejb.FinderException;
import javax.ejb.SessionBean;
import javax.ejb.SessionContext;
import javax.naming.InitialContext;
import javax.naming.NamingException;
import javax.rmi.PortableRemoteObject;
import javax.sql.DataSource;
import javax.transaction.SystemException;
import javax.transaction.UserTransaction;

import com.harbor.oms.product.Product;
import com.harbor.oms.product.ProductHome;
import com.harbor.oms.support.Money;
import com.harbor.oms.support.OmsException;
import com.harbor.oms.support.Regions;

/**
 * Region quotes from the product book, and buyer-approved price overrides.
 */
public class PricingServiceBean implements SessionBean {

    private SessionContext sessionContext;

    public void ejbCreate() throws RemoteException {
    }

    public void ejbRemove() throws RemoteException {
    }

    public void ejbActivate() throws RemoteException {
    }

    public void ejbPassivate() throws RemoteException {
    }

    public void setSessionContext(SessionContext context) throws RemoteException {
        this.sessionContext = context;
    }

    public long quote(String sku, String regionCode, int quantity) throws OmsException {
        if (quantity <= 0) {
            throw new OmsException("quantity must be positive");
        }
        long unit = priceBookForRegion(sku, regionCode);
        return Money.lineTotal(unit, quantity);
    }

    public void applyPriceOverride(String sku, long unitPriceCents) throws OmsException {
        if (sku == null || sku.length() == 0) {
            throw new OmsException("sku is required");
        }
        if (unitPriceCents < 0) {
            throw new OmsException("price must not be negative");
        }
        UserTransaction transaction = sessionContext.getUserTransaction();
        Connection connection = null;
        try {
            transaction.begin();
            connection = lookupOrderDataSource().getConnection();
            PreparedStatement statement = connection.prepareStatement(
                    "UPDATE product SET unit_price_cents = ? WHERE sku = ?");
            try {
                statement.setLong(1, unitPriceCents);
                statement.setString(2, sku);
                int updated = statement.executeUpdate();
                if (updated != 1) {
                    throw new OmsException("sku was not updated: " + sku);
                }
            } finally {
                statement.close();
            }
            transaction.commit();
        } catch (OmsException business) {
            rollbackOverride(transaction);
            throw business;
        } catch (Exception failure) {
            rollbackOverride(transaction);
            throw new EJBException("price override failed for " + sku, failure);
        } finally {
            close(connection);
        }
    }

    public long priceBookForRegion(String sku, String regionCode) throws OmsException {
        if (sku == null || sku.length() == 0) {
            throw new OmsException("sku is required");
        }
        try {
            Product product = productHome().findByPrimaryKey(sku);
            return Regions.adjust(product.getUnitPriceCents(), regionCode);
        } catch (FinderException missing) {
            throw new OmsException("unknown sku: " + sku);
        } catch (NamingException failure) {
            throw new EJBException("price book lookup failed", failure);
        } catch (RemoteException failure) {
            throw new EJBException("price book call failed", failure);
        }
    }

    private void rollbackOverride(UserTransaction transaction) {
        try {
            transaction.rollback();
        } catch (SystemException failure) {
            throw new EJBException("price override rollback failed", failure);
        }
    }

    private ProductHome productHome() throws NamingException {
        InitialContext naming = new InitialContext();
        Object bound = naming.lookup("java:comp/env/ejb/Product");
        return (ProductHome) PortableRemoteObject.narrow(
                bound, ProductHome.class);
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
