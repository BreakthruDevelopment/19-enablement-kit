/*
 * Harbor OMS. Synthetic order-management code written for this repository.
 */
package com.harbor.oms.customer;

import java.rmi.RemoteException;

import javax.ejb.EJBObject;

import com.harbor.oms.support.OmsException;

/**
 * A buyer the order desk can sell to. Credit and hold status live on this row.
 */
public interface Customer extends EJBObject {

    /** @return the stored customer_id */
    String getCustomerId() throws RemoteException;

    /** @return the stored legal_name */
    String getLegalName() throws RemoteException;

    /** Store a new legal_name. */
    void setLegalName(String value) throws RemoteException;

    /** @return the stored region_code */
    String getRegionCode() throws RemoteException;

    /** Store a new region_code. */
    void setRegionCode(String value) throws RemoteException;

    /** @return the stored credit_limit_cents */
    long getCreditLimitCents() throws RemoteException;

    /** Store a new credit_limit_cents. */
    void setCreditLimitCents(long value) throws RemoteException;

    /** @return the stored status_code */
    String getStatusCode() throws RemoteException;

    /** Store a new status_code. */
    void setStatusCode(String value) throws RemoteException;

    /** @return the stored buyer_name */
    String getBuyerName() throws RemoteException;

    /** Store a new buyer_name. */
    void setBuyerName(String value) throws RemoteException;

    /** @return the stored city */
    String getCity() throws RemoteException;

    /** Store a new city. */
    void setCity(String value) throws RemoteException;

    /** @return the stored opened_on */
    String getOpenedOn() throws RemoteException;

    /** Store a new opened_on. */
    void setOpenedOn(String value) throws RemoteException;

    void placeOnHold(String reason) throws OmsException, RemoteException;

    void releaseHold() throws OmsException, RemoteException;
}
