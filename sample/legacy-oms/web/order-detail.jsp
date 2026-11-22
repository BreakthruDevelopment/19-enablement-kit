<%@ page contentType="text/html; charset=UTF-8" %>
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8"/>
  <title>Order accepted</title>
</head>
<body>
  <h1>Harbor order desk</h1>
  <h2>Order accepted</h2>
  <p>
    <a href="index.jsp">Home</a>
    | <a href="order-entry.jsp">New order</a>
    | <a href="order-list.jsp">Order status</a>
  </p>
  <%
    String orderId = (String) request.getAttribute("orderId");
    String customerId = (String) request.getAttribute("customerId");
    String sku = (String) request.getAttribute("sku");
    if (orderId == null) {
        orderId = "";
    }
    if (customerId == null) {
        customerId = "";
    }
    if (sku == null) {
        sku = "";
    }
  %>
  <p>Order <strong><%= orderId %></strong></p>
  <p>Customer <%= customerId %>, sku <%= sku %>.</p>
  <p>The desk has reserved the quantity and stored the buyer PO.</p>
  <hr/>
  <p>Pier office, doors 1 to 4. Stored prices are whole cents.</p>
</body>
</html>
