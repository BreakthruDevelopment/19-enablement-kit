/*
 * Harbor OMS. Synthetic order-management code written for this repository.
 */
package com.harbor.oms.shipment;

import java.rmi.RemoteException;

import javax.ejb.CreateException;
import javax.ejb.EJBHome;
import javax.ejb.FinderException;

/**
 * Home for Shipment. Keys are strings.
 */
public interface ShipmentHome extends EJBHome {

    Shipment create(String shipmentId, String orderId, String carrier, String trackingNo, String shippedOn, String statusCode, int weightGrams, String dockDoor) throws CreateException, RemoteException;

    Shipment findByPrimaryKey(String key) throws FinderException, RemoteException;
}
