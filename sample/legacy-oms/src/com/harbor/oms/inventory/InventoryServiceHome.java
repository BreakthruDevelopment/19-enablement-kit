/*
 * Harbor OMS. Synthetic order-management code written for this repository.
 */
package com.harbor.oms.inventory;

import java.rmi.RemoteException;

import javax.ejb.CreateException;
import javax.ejb.EJBHome;

/**
 * On-hand quantity, reservations and the reorder list for one warehouse.
 */
public interface InventoryServiceHome extends EJBHome {

    InventoryService create() throws CreateException, RemoteException;
}
