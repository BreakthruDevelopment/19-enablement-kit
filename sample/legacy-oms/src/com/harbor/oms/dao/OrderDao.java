/*
 * Harbor OMS. Synthetic order-management code written for this repository.
 */
package com.harbor.oms.dao;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.List;

import com.harbor.oms.order.OrderLine;

/**
 * JDBC access to sales_order. Callers pass an open connection and close it.
 */
public final class OrderDao {

    /** Column holder passed between the bean and this DAO. */
    public static final class Row {
        private String orderId;
        private String customerId;
        private String statusCode;
        private String placedOn;
        private String requestedShip;
        private long totalCents;
        private String currencyCode;
        private String buyerPo;
        private String warehouseCode;
        private String lineSku;
        private int lineQuantity;

        /**
         * Return the stored order_id.
         */
        public String getOrderId() {
            return orderId;
        }

        /**
         * Replace the stored order_id.
         */
        public void setOrderId(String value) {
            this.orderId = value;
        }

        /**
         * Return the stored customer_id.
         */
        public String getCustomerId() {
            return customerId;
        }

        /**
         * Replace the stored customer_id.
         */
        public void setCustomerId(String value) {
            this.customerId = value;
        }

        /**
         * Return the stored status_code.
         */
        public String getStatusCode() {
            return statusCode;
        }

        /**
         * Replace the stored status_code.
         */
        public void setStatusCode(String value) {
            this.statusCode = value;
        }

        /**
         * Return the stored placed_on.
         */
        public String getPlacedOn() {
            return placedOn;
        }

        /**
         * Replace the stored placed_on.
         */
        public void setPlacedOn(String value) {
            this.placedOn = value;
        }

        /**
         * Return the stored requested_ship.
         */
        public String getRequestedShip() {
            return requestedShip;
        }

        /**
         * Replace the stored requested_ship.
         */
        public void setRequestedShip(String value) {
            this.requestedShip = value;
        }

        /**
         * Return the stored total_cents.
         */
        public long getTotalCents() {
            return totalCents;
        }

        /**
         * Replace the stored total_cents.
         */
        public void setTotalCents(long value) {
            this.totalCents = value;
        }

        /**
         * Return the stored currency_code.
         */
        public String getCurrencyCode() {
            return currencyCode;
        }

        /**
         * Replace the stored currency_code.
         */
        public void setCurrencyCode(String value) {
            this.currencyCode = value;
        }

        /**
         * Return the stored buyer_po.
         */
        public String getBuyerPo() {
            return buyerPo;
        }

        /**
         * Replace the stored buyer_po.
         */
        public void setBuyerPo(String value) {
            this.buyerPo = value;
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
         * Return the stored line_sku.
         */
        public String getLineSku() {
            return lineSku;
        }

        /**
         * Replace the stored line_sku.
         */
        public void setLineSku(String value) {
            this.lineSku = value;
        }

        /**
         * Return the stored line_quantity.
         */
        public int getLineQuantity() {
            return lineQuantity;
        }

        /**
         * Replace the stored line_quantity.
         */
        public void setLineQuantity(int value) {
            this.lineQuantity = value;
        }

    }

    public OrderDao() {
    }

    public void insert(Connection connection, Row row) throws SQLException {
        PreparedStatement statement = connection.prepareStatement(
                "INSERT INTO sales_order (order_id, "
                        + "customer_id, status_code, placed_on, "
                        + "requested_ship, total_cents, currency_code, "
                        + "buyer_po, warehouse_code, line_sku, "
                        + "line_quantity) VALUES (?, ?, ?, ?, ?, ?, ?, "
                        + "?, ?, ?, ?)");
        try {
            statement.setString(1, row.getOrderId());
            statement.setString(2, row.getCustomerId());
            statement.setString(3, row.getStatusCode());
            statement.setString(4, row.getPlacedOn());
            statement.setString(5, row.getRequestedShip());
            statement.setLong(6, row.getTotalCents());
            statement.setString(7, row.getCurrencyCode());
            statement.setString(8, row.getBuyerPo());
            statement.setString(9, row.getWarehouseCode());
            statement.setString(10, row.getLineSku());
            statement.setInt(11, row.getLineQuantity());
            statement.executeUpdate();
        } finally {
            statement.close();
        }
    }

    public void update(Connection connection, Row row) throws SQLException {
        PreparedStatement statement = connection.prepareStatement(
                "UPDATE sales_order SET customer_id = ?, "
                        + "status_code = ?, placed_on = ?, "
                        + "requested_ship = ?, total_cents = ?, "
                        + "currency_code = ?, buyer_po = ?, "
                        + "warehouse_code = ?, line_sku = ?, "
                        + "line_quantity = ? WHERE order_id = ?");
        try {
            statement.setString(1, row.getCustomerId());
            statement.setString(2, row.getStatusCode());
            statement.setString(3, row.getPlacedOn());
            statement.setString(4, row.getRequestedShip());
            statement.setLong(5, row.getTotalCents());
            statement.setString(6, row.getCurrencyCode());
            statement.setString(7, row.getBuyerPo());
            statement.setString(8, row.getWarehouseCode());
            statement.setString(9, row.getLineSku());
            statement.setInt(10, row.getLineQuantity());
            statement.setString(11, row.getOrderId());
            statement.executeUpdate();
        } finally {
            statement.close();
        }
    }

    public int delete(Connection connection, String key) throws SQLException {
        PreparedStatement statement = connection.prepareStatement(
                "DELETE FROM sales_order WHERE order_id = ?");
        try {
            statement.setString(1, key);
            return statement.executeUpdate();
        } finally {
            statement.close();
        }
    }

    public Row findById(Connection connection, String key) throws SQLException {
        PreparedStatement statement = connection.prepareStatement(
                "SELECT order_id, customer_id, status_code, "
                        + "placed_on, requested_ship, total_cents, "
                        + "currency_code, buyer_po, warehouse_code, "
                        + "line_sku, line_quantity FROM sales_order "
                        + "WHERE order_id = ?");
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

    public List<Row> findByCustomerAndStatus(
            Connection connection, String customerId, String statusCode)
            throws SQLException {
        String sql = "SELECT order_id, customer_id, status_code, placed_on, "
                + "requested_ship, total_cents, currency_code, buyer_po, "
                + "warehouse_code, line_sku, line_quantity "
                + "FROM sales_order WHERE customer_id = '" + customerId + "' "
                + "AND status_code = '" + statusCode + "' "
                + "ORDER BY placed_on";
        Statement statement = connection.createStatement();
        try {
            ResultSet rows = statement.executeQuery(sql);
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

    public void insertLine(Connection connection, String orderId, OrderLine line)
            throws SQLException {
        PreparedStatement statement = connection.prepareStatement(
                "INSERT INTO order_line (order_id, line_no, "
                        + "sku, quantity, unit_price_cents) VALUES (?, "
                        + "1, ?, ?, ?)");
        try {
            statement.setString(1, orderId);
            statement.setString(2, line.getSku());
            statement.setInt(3, line.getQuantity());
            statement.setLong(4, line.getUnitPriceCents());
            statement.executeUpdate();
        } finally {
            statement.close();
        }
    }

    private Row read(ResultSet rows) throws SQLException {
        Row row = new Row();
        row.setOrderId(rows.getString(1));
        row.setCustomerId(rows.getString(2));
        row.setStatusCode(rows.getString(3));
        row.setPlacedOn(rows.getString(4));
        row.setRequestedShip(rows.getString(5));
        row.setTotalCents(rows.getLong(6));
        row.setCurrencyCode(rows.getString(7));
        row.setBuyerPo(rows.getString(8));
        row.setWarehouseCode(rows.getString(9));
        row.setLineSku(rows.getString(10));
        row.setLineQuantity(rows.getInt(11));
        return row;
    }
}
