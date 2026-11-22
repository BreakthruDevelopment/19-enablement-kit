/*
 * Harbor OMS. Synthetic order-management code written for this repository.
 */
package com.harbor.oms.product;

import java.rmi.RemoteException;

import javax.ejb.EJBObject;

import com.harbor.oms.support.OmsException;

/**
 * A sku stocked in one warehouse. The desk reserves quantity off on_hand.
 */
public interface Product extends EJBObject {

    /** @return the stored sku */
    String getSku() throws RemoteException;

    /** @return the stored description */
    String getDescription() throws RemoteException;

    /** Store a new description. */
    void setDescription(String value) throws RemoteException;

    /** @return the stored unit_price_cents */
    long getUnitPriceCents() throws RemoteException;

    /** Store a new unit_price_cents. */
    void setUnitPriceCents(long value) throws RemoteException;

    /** @return the stored on_hand */
    int getOnHand() throws RemoteException;

    /** Store a new on_hand. */
    void setOnHand(int value) throws RemoteException;

    /** @return the stored warehouse_code */
    String getWarehouseCode() throws RemoteException;

    /** Store a new warehouse_code. */
    void setWarehouseCode(String value) throws RemoteException;

    /** @return the stored reorder_point */
    int getReorderPoint() throws RemoteException;

    /** Store a new reorder_point. */
    void setReorderPoint(int value) throws RemoteException;

    /** @return the stored active_flag */
    String getActiveFlag() throws RemoteException;

    /** Store a new active_flag. */
    void setActiveFlag(String value) throws RemoteException;

    /** @return the stored vendor_code */
    String getVendorCode() throws RemoteException;

    /** Store a new vendor_code. */
    void setVendorCode(String value) throws RemoteException;

    void reserve(int quantity) throws OmsException, RemoteException;

    void release(int quantity) throws OmsException, RemoteException;
}
