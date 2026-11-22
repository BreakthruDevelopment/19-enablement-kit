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
 * JDBC access to shipment. Callers pass an open connection and close it.
 */
public final class ShipmentDao {

    /** Column holder passed between the bean and this DAO. */
    public static final class Row {
        private String shipmentId;
        private String orderId;
        private String carrier;
        private String trackingNo;
        private String shippedOn;
        private String statusCode;
        private int weightGrams;
        private String dockDoor;

        /**
         * Return the stored shipment_id.
         */
        public String getShipmentId() {
            return shipmentId;
        }

        /**
         * Replace the stored shipment_id.
         */
        public void setShipmentId(String value) {
            this.shipmentId = value;
        }

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
         * Return the stored carrier.
         */
        public String getCarrier() {
            return carrier;
        }

        /**
         * Replace the stored carrier.
         */
        public void setCarrier(String value) {
            this.carrier = value;
        }

        /**
         * Return the stored tracking_no.
         */
        public String getTrackingNo() {
            return trackingNo;
        }

        /**
         * Replace the stored tracking_no.
         */
        public void setTrackingNo(String value) {
            this.trackingNo = value;
        }

        /**
         * Return the stored shipped_on.
         */
        public String getShippedOn() {
            return shippedOn;
        }

        /**
         * Replace the stored shipped_on.
         */
        public void setShippedOn(String value) {
            this.shippedOn = value;
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
         * Return the stored weight_grams.
         */
        public int getWeightGrams() {
            return weightGrams;
        }

        /**
         * Replace the stored weight_grams.
         */
        public void setWeightGrams(int value) {
            this.weightGrams = value;
        }

        /**
         * Return the stored dock_door.
         */
        public String getDockDoor() {
            return dockDoor;
        }

        /**
         * Replace the stored dock_door.
         */
        public void setDockDoor(String value) {
            this.dockDoor = value;
        }

    }

    public ShipmentDao() {
    }

    public void insert(Connection connection, Row row) throws SQLException {
        PreparedStatement statement = connection.prepareStatement(
                "INSERT INTO shipment (shipment_id, order_id, "
                        + "carrier, tracking_no, shipped_on, "
                        + "status_code, weight_grams, dock_door) VALUES "
                        + "(?, ?, ?, ?, ?, ?, ?, ?)");
        try {
            statement.setString(1, row.getShipmentId());
            statement.setString(2, row.getOrderId());
            statement.setString(3, row.getCarrier());
            statement.setString(4, row.getTrackingNo());
            statement.setString(5, row.getShippedOn());
            statement.setString(6, row.getStatusCode());
            statement.setInt(7, row.getWeightGrams());
            statement.setString(8, row.getDockDoor());
            statement.executeUpdate();
        } finally {
            statement.close();
        }
    }

    public void update(Connection connection, Row row) throws SQLException {
        PreparedStatement statement = connection.prepareStatement(
                "UPDATE shipment SET order_id = ?, carrier = "
                        + "?, tracking_no = ?, shipped_on = ?, "
                        + "status_code = ?, weight_grams = ?, dock_door "
                        + "= ? WHERE shipment_id = ?");
        try {
            statement.setString(1, row.getOrderId());
            statement.setString(2, row.getCarrier());
            statement.setString(3, row.getTrackingNo());
            statement.setString(4, row.getShippedOn());
            statement.setString(5, row.getStatusCode());
            statement.setInt(6, row.getWeightGrams());
            statement.setString(7, row.getDockDoor());
            statement.setString(8, row.getShipmentId());
            statement.executeUpdate();
        } finally {
            statement.close();
        }
    }

    public int delete(Connection connection, String key) throws SQLException {
        PreparedStatement statement = connection.prepareStatement(
                "DELETE FROM shipment WHERE shipment_id = ?");
        try {
            statement.setString(1, key);
            return statement.executeUpdate();
        } finally {
            statement.close();
        }
    }

    public Row findById(Connection connection, String key) throws SQLException {
        PreparedStatement statement = connection.prepareStatement(
                "SELECT shipment_id, order_id, carrier, "
                        + "tracking_no, shipped_on, status_code, "
                        + "weight_grams, dock_door FROM shipment WHERE "
                        + "shipment_id = ?");
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

    public List<Row> findByOrder(Connection connection, String orderId)
            throws SQLException {
        PreparedStatement statement = connection.prepareStatement(
                "SELECT shipment_id, order_id, carrier, "
                        + "tracking_no, shipped_on, status_code, "
                        + "weight_grams, dock_door FROM shipment WHERE "
                        + "order_id = ? ORDER BY shipment_id");
        try {
            statement.setString(1, orderId);
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
        row.setShipmentId(rows.getString(1));
        row.setOrderId(rows.getString(2));
        row.setCarrier(rows.getString(3));
        row.setTrackingNo(rows.getString(4));
        row.setShippedOn(rows.getString(5));
        row.setStatusCode(rows.getString(6));
        row.setWeightGrams(rows.getInt(7));
        row.setDockDoor(rows.getString(8));
        return row;
    }
}
