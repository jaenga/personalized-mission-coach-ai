/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx,ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        jeju: ['"EF_jejudoldam"', "serif"],
        sejong: ['"SejongGeulggot"', "sans-serif"],
        noto: ['"Noto Sans KR"', '"Apple SD Gothic Neo"', "sans-serif"],
      },
      colors: {
        tomato: {
          DEFAULT: "#E35D49",
          light: "#F07A68",
          dark: "#C44A38",
        },
        leaf: "#7BC043",
        cream: "#FFF8F0",
      },
    },
  },
  plugins: [],
};
