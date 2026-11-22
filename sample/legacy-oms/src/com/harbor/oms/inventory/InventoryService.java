/*
 * Harbor OMS. Synthetic order-management code written for this repository.
 */
package com.harbor.oms.inventory;

import java.rmi.RemoteException;

import javax.ejb.EJBObject;

import com.harbor.oms.support.OmsException;

/**
 * On-hand quantity, reservations and the reorder list for one warehouse.
 */
public interface InventoryService extends EJBObject {

    int onHand(String sku) throws OmsException, RemoteException;

    void reserveStock(String sku, int quantity) throws OmsException, RemoteException;

    void releaseStock(String sku, int quantity) throws OmsException, RemoteException;

    String belowReorder(String warehouseCode) throws OmsException, RemoteException;
}
