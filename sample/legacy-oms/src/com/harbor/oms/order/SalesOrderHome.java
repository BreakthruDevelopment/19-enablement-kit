/*
 * Harbor OMS. Synthetic order-management code written for this repository.
 */
package com.harbor.oms.order;

import java.rmi.RemoteException;

import javax.ejb.CreateException;
import javax.ejb.EJBHome;
import javax.ejb.FinderException;

/**
 * Home for SalesOrder. Keys are strings.
 */
public interface SalesOrderHome extends EJBHome {

    SalesOrder create(String orderId, String customerId, String statusCode, String placedOn, String requestedShip, long totalCents, String currencyCode, String buyerPo, String warehouseCode, String lineSku, int lineQuantity) throws CreateException, RemoteException;

    SalesOrder findByPrimaryKey(String key) throws FinderException, RemoteException;
}
