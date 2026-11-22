/*
 * Harbor OMS. Synthetic order-management code written for this repository.
 */
package com.harbor.oms.support;

/** A business failure the order desk can show to a clerk. */
public class OmsException extends Exception {

    private static final long serialVersionUID = 1L;

    public OmsException(String message) {
        super(message);
    }
}
