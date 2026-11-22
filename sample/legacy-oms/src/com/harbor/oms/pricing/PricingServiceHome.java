/*
 * Harbor OMS. Synthetic order-management code written for this repository.
 */
package com.harbor.oms.pricing;

import java.rmi.RemoteException;

import javax.ejb.CreateException;
import javax.ejb.EJBHome;

/**
 * Region quotes from the product book, and buyer-approved price overrides.
 */
public interface PricingServiceHome extends EJBHome {

    PricingService create() throws CreateException, RemoteException;
}
