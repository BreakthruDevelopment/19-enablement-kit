/*
 * Harbor OMS. Synthetic order-management code written for this repository.
 */
package com.harbor.oms.pricing;

import java.rmi.RemoteException;

import javax.ejb.EJBObject;

import com.harbor.oms.support.OmsException;

/**
 * Region quotes from the product book, and buyer-approved price overrides.
 */
public interface PricingService extends EJBObject {

    long quote(String sku, String regionCode, int quantity) throws OmsException, RemoteException;

    void applyPriceOverride(String sku, long unitPriceCents) throws OmsException, RemoteException;

    long priceBookForRegion(String sku, String regionCode) throws OmsException, RemoteException;
}
