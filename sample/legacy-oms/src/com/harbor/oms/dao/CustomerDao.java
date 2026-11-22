/*
 * Harbor OMS. Synthetic order-management code written for this repository.
 */
package com.harbor.oms.dao;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;

/**
 * JDBC access to customer. Callers pass an open connection and close it.
 */
public final class CustomerDao {

    /** Column holder passed between the bean and this DAO. */
    public static final class Row {
        private String customerId;
        private String legalName;
        private String regionCode;
        private long creditLimitCents;
        private String statusCode;
        private String buyerName;
        private String city;
        private String openedOn;

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
         * Return the stored legal_name.
         */
        public String getLegalName() {
            return legalName;
        }

        /**
         * Replace the stored legal_name.
         */
        public void setLegalName(String value) {
            this.legalName = value;
        }

        /**
         * Return the stored region_code.
         */
        public String getRegionCode() {
            return regionCode;
        }

        /**
         * Replace the stored region_code.
         */
        public void setRegionCode(String value) {
            this.regionCode = value;
        }

        /**
         * Return the stored credit_limit_cents.
         */
        public long getCreditLimitCents() {
            return creditLimitCents;
        }

        /**
         * Replace the stored credit_limit_cents.
         */
        public void setCreditLimitCents(long value) {
            this.creditLimitCents = value;
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
         * Return the stored buyer_name.
         */
        public String getBuyerName() {
            return buyerName;
        }

        /**
         * Replace the stored buyer_name.
         */
        public void setBuyerName(String value) {
            this.buyerName = value;
        }

        /**
         * Return the stored city.
         */
        public String getCity() {
            return city;
        }

        /**
         * Replace the stored city.
         */
        public void setCity(String value) {
            this.city = value;
        }

        /**
         * Return the stored opened_on.
         */
        public String getOpenedOn() {
            return openedOn;
        }

        /**
         * Replace the stored opened_on.
         */
        public void setOpenedOn(String value) {
            this.openedOn = value;
        }

    }

    public CustomerDao() {
    }

    public void insert(Connection connection, Row row) throws SQLException {
        PreparedStatement statement = connection.prepareStatement(
                "INSERT INTO customer (customer_id, "
                        + "legal_name, region_code, credit_limit_cents, "
                        + "status_code, buyer_name, city, opened_on) "
                        + "VALUES (?, ?, ?, ?, ?, ?, ?, ?)");
        try {
            statement.setString(1, row.getCustomerId());
            statement.setString(2, row.getLegalName());
            statement.setString(3, row.getRegionCode());
            statement.setLong(4, row.getCreditLimitCents());
            statement.setString(5, row.getStatusCode());
            statement.setString(6, row.getBuyerName());
            statement.setString(7, row.getCity());
            statement.setString(8, row.getOpenedOn());
            statement.executeUpdate();
        } finally {
            statement.close();
        }
    }

    public void update(Connection connection, Row row) throws SQLException {
        PreparedStatement statement = connection.prepareStatement(
                "UPDATE customer SET legal_name = ?, "
                        + "region_code = ?, credit_limit_cents = ?, "
                        + "status_code = ?, buyer_name = ?, city = ?, "
                        + "opened_on = ? WHERE customer_id = ?");
        try {
            statement.setString(1, row.getLegalName());
            statement.setString(2, row.getRegionCode());
            statement.setLong(3, row.getCreditLimitCents());
            statement.setString(4, row.getStatusCode());
            statement.setString(5, row.getBuyerName());
            statement.setString(6, row.getCity());
            statement.setString(7, row.getOpenedOn());
            statement.setString(8, row.getCustomerId());
            statement.executeUpdate();
        } finally {
            statement.close();
        }
    }

    public int delete(Connection connection, String key) throws SQLException {
        PreparedStatement statement = connection.prepareStatement(
                "DELETE FROM customer WHERE customer_id = ?");
        try {
            statement.setString(1, key);
            return statement.executeUpdate();
        } finally {
            statement.close();
        }
    }

    public Row findById(Connection connection, String key) throws SQLException {
        PreparedStatement statement = connection.prepareStatement(
                "SELECT customer_id, legal_name, region_code, "
                        + "credit_limit_cents, status_code, buyer_name, "
                        + "city, opened_on FROM customer WHERE "
                        + "customer_id = ?");
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


    private Row read(ResultSet rows) throws SQLException {
        Row row = new Row();
        row.setCustomerId(rows.getString(1));
        row.setLegalName(rows.getString(2));
        row.setRegionCode(rows.getString(3));
        row.setCreditLimitCents(rows.getLong(4));
        row.setStatusCode(rows.getString(5));
        row.setBuyerName(rows.getString(6));
        row.setCity(rows.getString(7));
        row.setOpenedOn(rows.getString(8));
        return row;
    }
}
