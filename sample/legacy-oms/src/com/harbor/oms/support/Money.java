/*
 * Harbor OMS. Synthetic order-management code written for this repository.
 */
package com.harbor.oms.support;

/** Whole-cent arithmetic for desk prices. */
public final class Money {

    private Money() {
    }

    public static long lineTotal(long unitPriceCents, int quantity) {
        if (unitPriceCents < 0 || quantity < 0) {
            throw new IllegalArgumentException("money inputs must not be negative");
        }
        return unitPriceCents * (long) quantity;
    }

    public static String format(long cents) {
        long whole = cents / 100;
        long fraction = Math.abs(cents % 100);
        String digits = Long.toString(fraction);
        if (fraction < 10) {
            digits = "0" + digits;
        }
        return Long.toString(whole) + "." + digits;
    }
}
