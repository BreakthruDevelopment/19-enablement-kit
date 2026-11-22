<%@ page contentType="text/html; charset=UTF-8" %>
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8"/>
  <title>Desk home</title>
</head>
<body>
  <h1>Harbor order desk</h1>
  <h2>Desk home</h2>
  <p>
    <a href="index.jsp">Home</a>
    | <a href="order-entry.jsp">New order</a>
    | <a href="order-list.jsp">Order status</a>
  </p>
  <ol>
    <li>Confirm the buyer is active before taking a sku.</li>
    <li>Reserve stock, then write the order with the buyer's PO.</li>
    <li>Stage a shipment only after the order is open.</li>
    <li>Mark the shipment shipped with a tracking number.</li>
    <li>Mark it delivered when the barge or wagon reports in.</li>
  </ol>
  <ul>
    <li><a href="<%= request.getContextPath() %>/orders/new">Place an order</a></li>
    <li><a href="<%= request.getContextPath() %>/orders/status">Look up orders</a></li>
    <li><a href="<%= request.getContextPath() %>/admin/catalog">Catalog desk</a></li>
  </ul>
  <hr/>
  <p>Pier office, doors 1 to 4. Stored prices are whole cents.</p>
</body>
</html>
