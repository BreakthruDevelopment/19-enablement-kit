/*
 * Harbor OMS. Synthetic order-management code written for this repository.
 */
package com.harbor.oms.support;

import com.harbor.oms.support.OmsException;

/** Region codes the price book knows. */
public final class Regions {

    public static final String NORTH = "NORTH";
    public static final String SOUTH = "SOUTH";
    public static final String EAST = "EAST";
    public static final String WEST = "WEST";

    private Regions() {
    }

    public static long adjust(long unitPriceCents, String regionCode)
            throws OmsException {
        if (regionCode == null || regionCode.length() == 0) {
            throw new OmsException("region is required");
        }
        if (NORTH.equals(regionCode)) {
            return unitPriceCents;
        }
        if (SOUTH.equals(regionCode)) {
            return unitPriceCents + (unitPriceCents * 3) / 100;
        }
        if (EAST.equals(regionCode)) {
            return unitPriceCents + (unitPriceCents * 2) / 100;
        }
        if (WEST.equals(regionCode)) {
            return unitPriceCents + unitPriceCents / 100;
        }
        throw new OmsException("unknown region: " + regionCode);
    }
}
