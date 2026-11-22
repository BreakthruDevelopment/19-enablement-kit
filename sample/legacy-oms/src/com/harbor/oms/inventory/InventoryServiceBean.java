/*
 * Harbor OMS. Synthetic order-management code written for this repository.
 */
package com.harbor.oms.inventory;

import java.rmi.RemoteException;
import java.sql.Connection;
import java.sql.SQLException;
import java.util.List;

import javax.ejb.EJBException;
import javax.ejb.FinderException;
import javax.ejb.SessionBean;
import javax.ejb.SessionContext;
import javax.naming.InitialContext;
import javax.naming.NamingException;
import javax.rmi.PortableRemoteObject;
import javax.sql.DataSource;

import com.harbor.oms.dao.ProductDao;
import com.harbor.oms.product.Product;
import com.harbor.oms.product.ProductHome;
import com.harbor.oms.support.OmsException;

/**
 * On-hand quantity, reservations and the reorder list for one warehouse.
 */
public class InventoryServiceBean implements SessionBean {

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

    public int onHand(String sku) throws OmsException {
        try {
            return productHome().findByPrimaryKey(sku).getOnHand();
        } catch (FinderException missing) {
            throw new OmsException("unknown sku: " + sku);
        } catch (NamingException failure) {
            throw new EJBException("on-hand lookup failed", failure);
        } catch (RemoteException failure) {
            throw new EJBException("on-hand call failed", failure);
        }
    }

    public void reserveStock(String sku, int quantity) throws OmsException {
        try {
            productHome().findByPrimaryKey(sku).reserve(quantity);
        } catch (OmsException business) {
            throw business;
        } catch (FinderException missing) {
            throw new OmsException("unknown sku: " + sku);
        } catch (NamingException failure) {
            throw new EJBException("reserve lookup failed", failure);
        } catch (RemoteException failure) {
            throw new EJBException("reserve call failed", failure);
        }
    }

    public void releaseStock(String sku, int quantity) throws OmsException {
        try {
            productHome().findByPrimaryKey(sku).release(quantity);
        } catch (OmsException business) {
            throw business;
        } catch (FinderException missing) {
            throw new OmsException("unknown sku: " + sku);
        } catch (NamingException failure) {
            throw new EJBException("release lookup failed", failure);
        } catch (RemoteException failure) {
            throw new EJBException("release call failed", failure);
        }
    }

    public String belowReorder(String warehouseCode) throws OmsException {
        if (warehouseCode == null || warehouseCode.length() == 0) {
            throw new OmsException("warehouse is required");
        }
        Connection connection = null;
        try {
            connection = lookupOrderDataSource().getConnection();
            List<ProductDao.Row> found = new ProductDao().findBelowReorder(
                    connection, warehouseCode);
            StringBuilder joined = new StringBuilder();
            for (int index = 0; index < found.size(); index++) {
                if (index > 0) {
                    joined.append(',');
                }
                joined.append(found.get(index).getSku());
            }
            return joined.toString();
        } catch (NamingException failure) {
            throw new EJBException("reorder lookup failed", failure);
        } catch (SQLException failure) {
            throw new EJBException("reorder query failed", failure);
        } finally {
            close(connection);
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
