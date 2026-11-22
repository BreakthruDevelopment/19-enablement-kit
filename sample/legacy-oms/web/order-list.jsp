<%@ page contentType="text/html; charset=UTF-8" %>
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8"/>
  <title>Order status</title>
</head>
<body>
  <h1>Harbor order desk</h1>
  <h2>Order status</h2>
  <p>
    <a href="index.jsp">Home</a>
    | <a href="order-entry.jsp">New order</a>
    | <a href="order-list.jsp">Order status</a>
  </p>
  <form method="post" action="<%= request.getContextPath() %>/orders/status">
    <p>Customer id<br/><input name="customerId"/></p>
    <p>Status<br/>
      <select name="statusCode">
        <option>OPEN</option>
        <option>ALLOCATED</option>
        <option>SHIPPED</option>
        <option>DELIVERED</option>
        <option>CANCELLED</option>
      </select>
    </p>
    <p><button type="submit">Find orders</button></p>
  </form>
  <%
    String orderList = (String) request.getAttribute("orderList");
    if (orderList == null) {
        orderList = "";
    }
  %>
  <h3>Matching orders</h3>
  <p><%= orderList %></p>
  <hr/>
  <p>Pier office, doors 1 to 4. Stored prices are whole cents.</p>
</body>
</html>
