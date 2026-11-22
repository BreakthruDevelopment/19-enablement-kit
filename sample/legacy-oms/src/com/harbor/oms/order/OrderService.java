/*
 * Harbor OMS. Synthetic order-management code written for this repository.
 */
package com.harbor.oms.order;

import java.rmi.RemoteException;

import javax.ejb.EJBObject;

import com.harbor.oms.support.OmsException;

/**
 * Places, cancels and looks up desk orders for an active buyer.
 */
public interface OrderService extends EJBObject {

    String placeOrder(String customerId, String sku, int quantity, String placedOn, String requestedShip, String buyerPo) throws OmsException, RemoteException;

    void cancelOrder(String orderId) throws OmsException, RemoteException;

    String findOrdersForCustomer(String customerId, String statusCode) throws OmsException, RemoteException;

    void attachBuyerPo(String orderId, String buyerPo) throws OmsException, RemoteException;
}
