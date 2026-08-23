import React from "react";
import ReactDOM from "react-dom/client";
import { BladeProvider, bladeTheme } from "@razorpay/blade/components";
import App from "./App";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <BladeProvider themeTokens={bladeTheme} colorScheme="light">
      <App />
    </BladeProvider>
  </React.StrictMode>
);
