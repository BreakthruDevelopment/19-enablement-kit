/*
 * Harbor OMS. Synthetic order-management code written for this repository.
 */
package com.harbor.oms.order;

import java.rmi.RemoteException;

import javax.ejb.CreateException;
import javax.ejb.EJBHome;

/**
 * Places, cancels and looks up desk orders for an active buyer.
 */
public interface OrderServiceHome extends EJBHome {

    OrderService create() throws CreateException, RemoteException;
}
