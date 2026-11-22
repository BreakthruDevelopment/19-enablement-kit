/*
 * Harbor OMS. Synthetic order-management code written for this repository.
 */
package com.harbor.oms.order;

import java.rmi.RemoteException;

import javax.ejb.EJBObject;

import com.harbor.oms.support.OmsException;

/**
 * One desk order for one sku. The line row is written with the order.
 */
public interface SalesOrder extends EJBObject {

    /** @return the stored order_id */
    String getOrderId() throws RemoteException;

    /** @return the stored customer_id */
    String getCustomerId() throws RemoteException;

    /** Store a new customer_id. */
    void setCustomerId(String value) throws RemoteException;

    /** @return the stored status_code */
    String getStatusCode() throws RemoteException;

    /** Store a new status_code. */
    void setStatusCode(String value) throws RemoteException;

    /** @return the stored placed_on */
    String getPlacedOn() throws RemoteException;

    /** Store a new placed_on. */
    void setPlacedOn(String value) throws RemoteException;

    /** @return the stored requested_ship */
    String getRequestedShip() throws RemoteException;

    /** Store a new requested_ship. */
    void setRequestedShip(String value) throws RemoteException;

    /** @return the stored total_cents */
    long getTotalCents() throws RemoteException;

    /** Store a new total_cents. */
    void setTotalCents(long value) throws RemoteException;

    /** @return the stored currency_code */
    String getCurrencyCode() throws RemoteException;

    /** Store a new currency_code. */
    void setCurrencyCode(String value) throws RemoteException;

    /** @return the stored buyer_po */
    String getBuyerPo() throws RemoteException;

    /** Store a new buyer_po. */
    void setBuyerPo(String value) throws RemoteException;

    /** @return the stored warehouse_code */
    String getWarehouseCode() throws RemoteException;

    /** Store a new warehouse_code. */
    void setWarehouseCode(String value) throws RemoteException;

    /** @return the stored line_sku */
    String getLineSku() throws RemoteException;

    /** Store a new line_sku. */
    void setLineSku(String value) throws RemoteException;

    /** @return the stored line_quantity */
    int getLineQuantity() throws RemoteException;

    /** Store a new line_quantity. */
    void setLineQuantity(int value) throws RemoteException;

    void cancel() throws OmsException, RemoteException;

    void attachBuyerPo(String buyerPo) throws OmsException, RemoteException;
}
