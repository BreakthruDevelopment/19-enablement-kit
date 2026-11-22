/*
 * Harbor OMS. Synthetic order-management code written for this repository.
 */
package com.harbor.oms.dao;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.List;

/**
 * JDBC access to product. Callers pass an open connection and close it.
 */
public final class ProductDao {

    /** Column holder passed between the bean and this DAO. */
    public static final class Row {
        private String sku;
        private String description;
        private long unitPriceCents;
        private int onHand;
        private String warehouseCode;
        private int reorderPoint;
        private String activeFlag;
        private String vendorCode;

        /**
         * Return the stored sku.
         */
        public String getSku() {
            return sku;
        }

        /**
         * Replace the stored sku.
         */
        public void setSku(String value) {
            this.sku = value;
        }

        /**
         * Return the stored description.
         */
        public String getDescription() {
            return description;
        }

        /**
         * Replace the stored description.
         */
        public void setDescription(String value) {
            this.description = value;
        }

        /**
         * Return the stored unit_price_cents.
         */
        public long getUnitPriceCents() {
            return unitPriceCents;
        }

        /**
         * Replace the stored unit_price_cents.
         */
        public void setUnitPriceCents(long value) {
            this.unitPriceCents = value;
        }

        /**
         * Return the stored on_hand.
         */
        public int getOnHand() {
            return onHand;
        }

        /**
         * Replace the stored on_hand.
         */
        public void setOnHand(int value) {
            this.onHand = value;
        }

        /**
         * Return the stored warehouse_code.
         */
        public String getWarehouseCode() {
            return warehouseCode;
        }

        /**
         * Replace the stored warehouse_code.
         */
        public void setWarehouseCode(String value) {
            this.warehouseCode = value;
        }

        /**
         * Return the stored reorder_point.
         */
        public int getReorderPoint() {
            return reorderPoint;
        }

        /**
         * Replace the stored reorder_point.
         */
        public void setReorderPoint(int value) {
            this.reorderPoint = value;
        }

        /**
         * Return the stored active_flag.
         */
        public String getActiveFlag() {
            return activeFlag;
        }

        /**
         * Replace the stored active_flag.
         */
        public void setActiveFlag(String value) {
            this.activeFlag = value;
        }

        /**
         * Return the stored vendor_code.
         */
        public String getVendorCode() {
            return vendorCode;
        }

        /**
         * Replace the stored vendor_code.
         */
        public void setVendorCode(String value) {
            this.vendorCode = value;
        }

    }

    public ProductDao() {
    }

    public void insert(Connection connection, Row row) throws SQLException {
        PreparedStatement statement = connection.prepareStatement(
                "INSERT INTO product (sku, description, "
                        + "unit_price_cents, on_hand, warehouse_code, "
                        + "reorder_point, active_flag, vendor_code) "
                        + "VALUES (?, ?, ?, ?, ?, ?, ?, ?)");
        try {
            statement.setString(1, row.getSku());
            statement.setString(2, row.getDescription());
            statement.setLong(3, row.getUnitPriceCents());
            statement.setInt(4, row.getOnHand());
            statement.setString(5, row.getWarehouseCode());
            statement.setInt(6, row.getReorderPoint());
            statement.setString(7, row.getActiveFlag());
            statement.setString(8, row.getVendorCode());
            statement.executeUpdate();
        } finally {
            statement.close();
        }
    }

    public void update(Connection connection, Row row) throws SQLException {
        PreparedStatement statement = connection.prepareStatement(
                "UPDATE product SET description = ?, "
                        + "unit_price_cents = ?, on_hand = ?, "
                        + "warehouse_code = ?, reorder_point = ?, "
                        + "active_flag = ?, vendor_code = ? WHERE sku = ?");
        try {
            statement.setString(1, row.getDescription());
            statement.setLong(2, row.getUnitPriceCents());
            statement.setInt(3, row.getOnHand());
            statement.setString(4, row.getWarehouseCode());
            statement.setInt(5, row.getReorderPoint());
            statement.setString(6, row.getActiveFlag());
            statement.setString(7, row.getVendorCode());
            statement.setString(8, row.getSku());
            statement.executeUpdate();
        } finally {
            statement.close();
        }
    }

    public int delete(Connection connection, String key) throws SQLException {
        PreparedStatement statement = connection.prepareStatement(
                "DELETE FROM product WHERE sku = ?");
        try {
            statement.setString(1, key);
            return statement.executeUpdate();
        } finally {
            statement.close();
        }
    }

    public Row findById(Connection connection, String key) throws SQLException {
        PreparedStatement statement = connection.prepareStatement(
                "SELECT sku, description, unit_price_cents, "
                        + "on_hand, warehouse_code, reorder_point, "
                        + "active_flag, vendor_code FROM product WHERE "
                        + "sku = ?");
        try {
            statement.setString(1, key);
            ResultSet rows = statement.executeQuery();
            try {
                if (!rows.next()) {
                    return null;
                }
                return read(rows);
            } finally {
                rows.close();
            }
        } finally {
            statement.close();
        }
    }

    public List<Row> findBelowReorder(Connection connection, String warehouseCode)
            throws SQLException {
        PreparedStatement statement = connection.prepareStatement(
                "SELECT sku, description, unit_price_cents, "
                        + "on_hand, warehouse_code, reorder_point, "
                        + "active_flag, vendor_code FROM product WHERE "
                        + "warehouse_code = ? AND on_hand <= "
                        + "reorder_point AND active_flag = 'Y' ORDER BY "
                        + "sku");
        try {
            statement.setString(1, warehouseCode);
            ResultSet rows = statement.executeQuery();
            try {
                List<Row> found = new ArrayList<Row>();
                while (rows.next()) {
                    found.add(read(rows));
                }
                return found;
            } finally {
                rows.close();
            }
        } finally {
            statement.close();
        }
    }

    private Row read(ResultSet rows) throws SQLException {
        Row row = new Row();
        row.setSku(rows.getString(1));
        row.setDescription(rows.getString(2));
        row.setUnitPriceCents(rows.getLong(3));
        row.setOnHand(rows.getInt(4));
        row.setWarehouseCode(rows.getString(5));
        row.setReorderPoint(rows.getInt(6));
        row.setActiveFlag(rows.getString(7));
        row.setVendorCode(rows.getString(8));
        return row;
    }
}
