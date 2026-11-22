/*
 * Harbor OMS. Synthetic order-management code written for this repository.
 */
package com.harbor.oms.catalog;

import java.rmi.RemoteException;

import javax.ejb.CreateException;
import javax.ejb.EJBHome;

/**
 * Adds skus, retires them and moves a sku between warehouses.
 */
public interface CatalogAdminHome extends EJBHome {

    CatalogAdmin create() throws CreateException, RemoteException;
}
