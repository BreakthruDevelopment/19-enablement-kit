/*
 * Harbor OMS. Synthetic order-management code written for this repository.
 */
package com.harbor.oms.product;

import java.rmi.RemoteException;

import javax.ejb.CreateException;
import javax.ejb.EJBHome;
import javax.ejb.FinderException;

/**
 * Home for Product. Keys are strings.
 */
public interface ProductHome extends EJBHome {

    Product create(String sku, String description, long unitPriceCents, int onHand, String warehouseCode, int reorderPoint, String activeFlag, String vendorCode) throws CreateException, RemoteException;

    Product findByPrimaryKey(String key) throws FinderException, RemoteException;
}
