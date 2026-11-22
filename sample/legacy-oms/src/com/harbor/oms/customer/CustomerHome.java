/*
 * Harbor OMS. Synthetic order-management code written for this repository.
 */
package com.harbor.oms.customer;

import java.rmi.RemoteException;

import javax.ejb.CreateException;
import javax.ejb.EJBHome;
import javax.ejb.FinderException;

/**
 * Home for Customer. Keys are strings.
 */
public interface CustomerHome extends EJBHome {

    Customer create(String customerId, String legalName, String regionCode, long creditLimitCents, String statusCode, String buyerName, String city, String openedOn) throws CreateException, RemoteException;

    Customer findByPrimaryKey(String key) throws FinderException, RemoteException;
}
