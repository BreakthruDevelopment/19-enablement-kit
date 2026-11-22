/*
 * Harbor OMS. Synthetic order-management code written for this repository.
 */
package com.harbor.oms.shipment;

import java.rmi.RemoteException;

import javax.ejb.EJBObject;

import com.harbor.oms.support.OmsException;

/**
 * A dock shipment against one order, from staged through delivered.
 */
public interface Shipment extends EJBObject {

    /** @return the stored shipment_id */
    String getShipmentId() throws RemoteException;

    /** @return the stored order_id */
    String getOrderId() throws RemoteException;

    /** Store a new order_id. */
    void setOrderId(String value) throws RemoteException;

    /** @return the stored carrier */
    String getCarrier() throws RemoteException;

    /** Store a new carrier. */
    void setCarrier(String value) throws RemoteException;

    /** @return the stored tracking_no */
    String getTrackingNo() throws RemoteException;

    /** Store a new tracking_no. */
    void setTrackingNo(String value) throws RemoteException;

    /** @return the stored shipped_on */
    String getShippedOn() throws RemoteException;

    /** Store a new shipped_on. */
    void setShippedOn(String value) throws RemoteException;

    /** @return the stored status_code */
    String getStatusCode() throws RemoteException;

    /** Store a new status_code. */
    void setStatusCode(String value) throws RemoteException;

    /** @return the stored weight_grams */
    int getWeightGrams() throws RemoteException;

    /** Store a new weight_grams. */
    void setWeightGrams(int value) throws RemoteException;

    /** @return the stored dock_door */
    String getDockDoor() throws RemoteException;

    /** Store a new dock_door. */
    void setDockDoor(String value) throws RemoteException;

    void markShipped(String trackingNo) throws OmsException, RemoteException;

    void markDelivered() throws OmsException, RemoteException;
}
