/*
 * Harbor OMS. Synthetic order-management code written for this repository.
 */
package com.harbor.oms.fulfillment;

import java.rmi.RemoteException;

import javax.ejb.CreateException;
import javax.ejb.EJBHome;

/**
 * Stages a shipment, marks it shipped and records delivery at the dock.
 */
public interface FulfillmentServiceHome extends EJBHome {

    FulfillmentService create() throws CreateException, RemoteException;
}
