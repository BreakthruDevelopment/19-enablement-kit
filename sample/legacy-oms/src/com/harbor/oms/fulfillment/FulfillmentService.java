/*
 * Harbor OMS. Synthetic order-management code written for this repository.
 */
package com.harbor.oms.fulfillment;

import java.rmi.RemoteException;

import javax.ejb.EJBObject;

import com.harbor.oms.support.OmsException;

/**
 * Stages a shipment, marks it shipped and records delivery at the dock.
 */
public interface FulfillmentService extends EJBObject {

    String createShipment(String orderId, String carrier) throws OmsException, RemoteException;

    void markShipped(String shipmentId, String trackingNo) throws OmsException, RemoteException;

    void markDelivered(String shipmentId) throws OmsException, RemoteException;

    String findShipments(String orderId) throws OmsException, RemoteException;
}
