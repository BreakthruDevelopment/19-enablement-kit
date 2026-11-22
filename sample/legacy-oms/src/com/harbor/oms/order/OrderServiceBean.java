/*
 * Harbor OMS. Synthetic order-management code written for this repository.
 */
package com.harbor.oms.order;

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

import com.harbor.oms.customer.Customer;
import com.harbor.oms.customer.CustomerHome;
import com.harbor.oms.dao.OrderDao;
import com.harbor.oms.product.Product;
import com.harbor.oms.product.ProductHome;
import com.harbor.oms.support.Money;
import com.harbor.oms.support.OmsException;

/**
 * Places, cancels and looks up desk orders for an active buyer.
 */
public class OrderServiceBean implements SessionBean {

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

    public String placeOrder(String customerId, String sku, int quantity, String placedOn, String requestedShip, String buyerPo) throws OmsException {
        if (customerId == null || customerId.length() == 0) {
            throw new OmsException("customer id is required");
        }
        if (sku == null || sku.length() == 0) {
            throw new OmsException("sku is required");
        }
        if (quantity <= 0) {
            throw new OmsException("quantity must be positive");
        }
        if (placedOn == null || placedOn.length() != 10) {
            throw new OmsException("placed-on must be yyyy-mm-dd");
        }
        if (requestedShip == null || requestedShip.length() != 10) {
            throw new OmsException("requested ship must be yyyy-mm-dd");
        }
        try {
            Customer customer = customerHome().findByPrimaryKey(customerId);
            if (!"ACTIVE".equals(customer.getStatusCode())) {
                throw new OmsException("customer cannot place orders: " + customerId);
            }
            Product product = productHome().findByPrimaryKey(sku);
            if (!"Y".equals(product.getActiveFlag())) {
                throw new OmsException("sku is not active: " + sku);
            }
            long lineCents = Money.lineTotal(product.getUnitPriceCents(), quantity);
            if (lineCents > customer.getCreditLimitCents()) {
                throw new OmsException("credit limit exceeded for " + customerId);
            }
            product.reserve(quantity);
            String orderId = customerId + "-" + placedOn + "-" + sku;
            SalesOrder created = salesOrderHome().create(
                    orderId,
                    customerId,
                    "OPEN",
                    placedOn,
                    requestedShip,
                    lineCents,
                    "USD",
                    buyerPo == null ? "" : buyerPo,
                    product.getWarehouseCode(),
                    sku,
                    quantity);
            return created.getOrderId();
        } catch (OmsException business) {
            throw business;
        } catch (FinderException missing) {
            throw new OmsException("unknown customer or sku");
        } catch (NamingException failure) {
            throw new EJBException("order desk naming failed", failure);
        } catch (RemoteException failure) {
            throw new EJBException("order desk remote call failed", failure);
        } catch (javax.ejb.CreateException failure) {
            throw new EJBException("order create failed", failure);
        }
    }

    public void cancelOrder(String orderId) throws OmsException {
        if (orderId == null || orderId.length() == 0) {
            throw new OmsException("order id is required");
        }
        try {
            SalesOrder order = salesOrderHome().findByPrimaryKey(orderId);
            String status = order.getStatusCode();
            if (!"OPEN".equals(status) && !"ALLOCATED".equals(status)) {
                throw new OmsException("order cannot be cancelled: " + orderId);
            }
            Product product = productHome().findByPrimaryKey(order.getLineSku());
            product.release(order.getLineQuantity());
            order.cancel();
        } catch (OmsException business) {
            throw business;
        } catch (FinderException missing) {
            throw new OmsException("unknown order: " + orderId);
        } catch (NamingException failure) {
            throw new EJBException("cancel lookup failed", failure);
        } catch (RemoteException failure) {
            throw new EJBException("cancel call failed", failure);
        }
    }

    public String findOrdersForCustomer(String customerId, String statusCode) throws OmsException {
        if (customerId == null || customerId.length() == 0) {
            throw new OmsException("customer id is required");
        }
        if (statusCode == null || statusCode.length() == 0) {
            throw new OmsException("status is required");
        }
        Connection connection = null;
        try {
            connection = lookupOrderDataSource().getConnection();
            List<OrderDao.Row> found = new OrderDao().findByCustomerAndStatus(
                    connection, customerId, statusCode);
            StringBuilder joined = new StringBuilder();
            for (int index = 0; index < found.size(); index++) {
                if (index > 0) {
                    joined.append(',');
                }
                joined.append(found.get(index).getOrderId());
            }
            return joined.toString();
        } catch (NamingException failure) {
            throw new EJBException("order search lookup failed", failure);
        } catch (SQLException failure) {
            throw new EJBException("order search failed", failure);
        } finally {
            close(connection);
        }
    }

    public void attachBuyerPo(String orderId, String buyerPo) throws OmsException {
        if (orderId == null || orderId.length() == 0) {
            throw new OmsException("order id is required");
        }
        try {
            salesOrderHome().findByPrimaryKey(orderId).attachBuyerPo(buyerPo);
        } catch (OmsException business) {
            throw business;
        } catch (FinderException missing) {
            throw new OmsException("unknown order: " + orderId);
        } catch (NamingException failure) {
            throw new EJBException("buyer PO lookup failed", failure);
        } catch (RemoteException failure) {
            throw new EJBException("buyer PO call failed", failure);
        }
    }

    private CustomerHome customerHome() throws NamingException {
        InitialContext naming = new InitialContext();
        Object bound = naming.lookup("java:comp/env/ejb/Customer");
        return (CustomerHome) PortableRemoteObject.narrow(
                bound, CustomerHome.class);
    }

    private ProductHome productHome() throws NamingException {
        InitialContext naming = new InitialContext();
        Object bound = naming.lookup("java:comp/env/ejb/Product");
        return (ProductHome) PortableRemoteObject.narrow(
                bound, ProductHome.class);
    }

    private SalesOrderHome salesOrderHome() throws NamingException {
        InitialContext naming = new InitialContext();
        Object bound = naming.lookup("java:comp/env/ejb/SalesOrder");
        return (SalesOrderHome) PortableRemoteObject.narrow(
                bound, SalesOrderHome.class);
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
