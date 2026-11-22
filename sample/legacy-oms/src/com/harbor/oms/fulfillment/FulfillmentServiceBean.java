/*
 * Harbor OMS. Synthetic order-management code written for this repository.
 */
package com.harbor.oms.fulfillment;

import java.rmi.RemoteException;
import java.sql.Connection;
import java.sql.SQLException;
import java.util.List;

import javax.ejb.CreateException;
import javax.ejb.EJBException;
import javax.ejb.FinderException;
import javax.ejb.SessionBean;
import javax.ejb.SessionContext;
import javax.naming.InitialContext;
import javax.naming.NamingException;
import javax.rmi.PortableRemoteObject;
import javax.sql.DataSource;

import com.harbor.oms.dao.ShipmentDao;
import com.harbor.oms.order.SalesOrder;
import com.harbor.oms.order.SalesOrderHome;
import com.harbor.oms.shipment.Shipment;
import com.harbor.oms.shipment.ShipmentHome;
import com.harbor.oms.support.OmsException;

/**
 * Stages a shipment, marks it shipped and records delivery at the dock.
 */
public class FulfillmentServiceBean implements SessionBean {

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

    public String createShipment(String orderId, String carrier) throws OmsException {
        if (orderId == null || orderId.length() == 0) {
            throw new OmsException("order id is required");
        }
        if (carrier == null || carrier.length() == 0) {
            throw new OmsException("carrier is required");
        }
        try {
            SalesOrder order = salesOrderHome().findByPrimaryKey(orderId);
            if (!"OPEN".equals(order.getStatusCode())) {
                throw new OmsException("order is not open for shipment: " + orderId);
            }
            String shipmentId = orderId + "-S1";
            Shipment created = shipmentHome().create(
                    shipmentId,
                    orderId,
                    carrier,
                    "",
                    "",
                    "STAGED",
                    0,
                    "DOOR-1");
            order.setStatusCode("ALLOCATED");
            return created.getShipmentId();
        } catch (OmsException business) {
            throw business;
        } catch (FinderException missing) {
            throw new OmsException("unknown order: " + orderId);
        } catch (CreateException failure) {
            throw new EJBException("shipment create failed", failure);
        } catch (NamingException failure) {
            throw new EJBException("shipment lookup failed", failure);
        } catch (RemoteException failure) {
            throw new EJBException("shipment call failed", failure);
        }
    }

    public void markShipped(String shipmentId, String trackingNo) throws OmsException {
        try {
            Shipment shipment = shipmentHome().findByPrimaryKey(shipmentId);
            shipment.markShipped(trackingNo);
            SalesOrder order = salesOrderHome().findByPrimaryKey(shipment.getOrderId());
            order.setStatusCode("SHIPPED");
        } catch (OmsException business) {
            throw business;
        } catch (FinderException missing) {
            throw new OmsException("unknown shipment: " + shipmentId);
        } catch (NamingException failure) {
            throw new EJBException("ship lookup failed", failure);
        } catch (RemoteException failure) {
            throw new EJBException("ship call failed", failure);
        }
    }

    public void markDelivered(String shipmentId) throws OmsException {
        try {
            Shipment shipment = shipmentHome().findByPrimaryKey(shipmentId);
            shipment.markDelivered();
            SalesOrder order = salesOrderHome().findByPrimaryKey(shipment.getOrderId());
            order.setStatusCode("DELIVERED");
        } catch (OmsException business) {
            throw business;
        } catch (FinderException missing) {
            throw new OmsException("unknown shipment: " + shipmentId);
        } catch (NamingException failure) {
            throw new EJBException("delivery lookup failed", failure);
        } catch (RemoteException failure) {
            throw new EJBException("delivery call failed", failure);
        }
    }

    public String findShipments(String orderId) throws OmsException {
        if (orderId == null || orderId.length() == 0) {
            throw new OmsException("order id is required");
        }
        Connection connection = null;
        try {
            connection = lookupOrderDataSource().getConnection();
            List<ShipmentDao.Row> found = new ShipmentDao()
                    .findByOrder(connection, orderId);
            StringBuilder joined = new StringBuilder();
            for (int index = 0; index < found.size(); index++) {
                if (index > 0) {
                    joined.append(',');
                }
                joined.append(found.get(index).getShipmentId());
            }
            return joined.toString();
        } catch (NamingException failure) {
            throw new EJBException("shipment search lookup failed", failure);
        } catch (SQLException failure) {
            throw new EJBException("shipment search failed", failure);
        } finally {
            close(connection);
        }
    }

    private SalesOrderHome salesOrderHome() throws NamingException {
        InitialContext naming = new InitialContext();
        Object bound = naming.lookup("java:comp/env/ejb/SalesOrder");
        return (SalesOrderHome) PortableRemoteObject.narrow(
                bound, SalesOrderHome.class);
    }

    private ShipmentHome shipmentHome() throws NamingException {
        InitialContext naming = new InitialContext();
        Object bound = naming.lookup("java:comp/env/ejb/Shipment");
        return (ShipmentHome) PortableRemoteObject.narrow(
                bound, ShipmentHome.class);
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
