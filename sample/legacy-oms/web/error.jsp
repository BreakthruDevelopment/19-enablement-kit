<%@ page contentType="text/html; charset=UTF-8" %>
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8"/>
  <title>Desk message</title>
</head>
<body>
  <h1>Harbor order desk</h1>
  <h2>Desk message</h2>
  <p>
    <a href="index.jsp">Home</a>
    | <a href="order-entry.jsp">New order</a>
    | <a href="order-list.jsp">Order status</a>
  </p>
  <%
    String deskMessage = (String) request.getAttribute("deskMessage");
    if (deskMessage == null) {
        deskMessage = "The desk could not complete that step.";
    }
  %>
  <p><%= deskMessage %></p>
  <hr/>
  <p>Pier office, doors 1 to 4. Stored prices are whole cents.</p>
</body>
</html>
