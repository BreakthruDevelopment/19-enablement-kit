/*
 * Harbor OMS. Synthetic order-management code written for this repository.
 */
package com.harbor.oms.catalog;

import java.rmi.RemoteException;

import javax.ejb.EJBObject;

import com.harbor.oms.support.OmsException;

/**
 * Adds skus, retires them and moves a sku between warehouses.
 */
public interface CatalogAdmin extends EJBObject {

    void addProduct(String sku, String description, long unitPriceCents, String warehouseCode, String vendorCode) throws OmsException, RemoteException;

    void discontinueProduct(String sku) throws OmsException, RemoteException;

    void updateWarehouse(String sku, String warehouseCode) throws OmsException, RemoteException;
}
