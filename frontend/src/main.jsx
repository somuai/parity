import React from "react";
import ReactDOM from "react-dom/client";
import { BladeProvider } from "@razorpay/blade/components";
import { bladeTheme } from "@razorpay/blade/tokens";
import { createGlobalStyle } from "styled-components";
import App from "./App";

const GlobalStyle = createGlobalStyle`
  *, *::before, *::after {
    box-sizing: border-box;
  }

  html, body, #root {
    min-height: 100%;
  }

  body {
    margin: ${({ theme }) => theme.spacing[0]};
    background: ${({ theme }) => theme.colors.surface.background.gray.subtle};
  }
`;

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <BladeProvider themeTokens={bladeTheme} colorScheme="light">
      <GlobalStyle />
      <App />
    </BladeProvider>
  </React.StrictMode>
);
