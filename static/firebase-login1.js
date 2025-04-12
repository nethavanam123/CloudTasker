// Import the functions you need from the Firebase SDKs
import { initializeApp } from "https://www.gstatic.com/firebasejs/10.8.0/firebase-app.js";
import {
  getAuth,
  createUserWithEmailAndPassword,
  signInWithEmailAndPassword,
  onAuthStateChanged,
  signOut,
  getIdToken
} from "https://www.gstatic.com/firebasejs/10.8.0/firebase-auth.js";

// Firebase configuration
const firebaseConfig = {
    apiKey: "AIzaSyAJSR0FYq_E3jnVRNMJKOgmUxZFxtBvx6c",
    authDomain: "cloudtasker-211ae.firebaseapp.com",
    projectId: "cloudtasker-211ae",
    storageBucket: "cloudtasker-211ae.firebasestorage.app",
    messagingSenderId: "60591379083",
    appId: "1:60591379083:web:107685ee8fde91ca6efa8e"
  };

// Initialize Firebase
const app = initializeApp(firebaseConfig);
const auth = getAuth(app);

// Helper: Set cookie
const setTokenCookie = async (user) => {
  const idToken = await getIdToken(user, true);
  document.cookie = `token=${idToken}; path=/`;
};

// DOM Elements
const emailInput = document.getElementById("email");
const passwordInput = document.getElementById("password");
const loginBtn = document.getElementById("login");
const signUpBtn = document.getElementById("sign-up");
const signOutBtn = document.getElementById("sign-out");

// Login
if (loginBtn) {
  loginBtn.addEventListener("click", async () => {
    const email = emailInput.value;
    const password = passwordInput.value;

    try {
      const userCredential = await signInWithEmailAndPassword(auth, email, password);
      await setTokenCookie(userCredential.user);
      window.location.href = "/";
    } catch (error) {
      console.error("Login error:", error.message);
      alert("Login failed: " + error.message);
    }
  });
}

// Sign Up
if (signUpBtn) {
  signUpBtn.addEventListener("click", async () => {
    const email = emailInput.value;
    const password = passwordInput.value;

    try {
      const userCredential = await createUserWithEmailAndPassword(auth, email, password);
      await setTokenCookie(userCredential.user);
      window.location.href = "/";
    } catch (error) {
      console.error("Signup error:", error.message);
      alert("Signup failed: " + error.message);
    }
  });
}

// Sign Out
if (signOutBtn) {
  signOutBtn.addEventListener("click", async () => {
    try {
      await signOut(auth);
      document.cookie = "token=; Max-Age=0; path=/";
      window.location.href = "/";
    } catch (error) {
      console.error("Sign out error:", error.message);
    }
  });
}

// Auto-show logout button if logged in
onAuthStateChanged(auth, (user) => {
  if (user && signOutBtn) {
    signOutBtn.hidden = false;
  }
});

// Add Firestore imports
import {
  getFirestore,
  doc,
  setDoc
} from "https://www.gstatic.com/firebasejs/10.8.0/firebase-firestore.js";

// Firestore init
const db = getFirestore(app);

// After successful sign-up
if (signUpBtn) {
  signUpBtn.addEventListener("click", async () => {
    const email = emailInput.value;
    const password = passwordInput.value;

    try {
      const userCredential = await createUserWithEmailAndPassword(auth, email, password);
      const user = userCredential.user;

      // Add user to Firestore 'users' collection
      await setDoc(doc(db, "users", user.uid), {
        id: user.uid,
        email: user.email,
        created_at: new Date().toISOString()
      });

      await setTokenCookie(user);
      window.location.href = "/";
    } catch (error) {
      console.error("Signup error:", error.message);
      alert("Signup failed: " + error.message);
    }
  });
}

// Sign Up
if (signUpBtn) {
  signUpBtn.addEventListener("click", async () => {
    const email = emailInput.value;
    const password = passwordInput.value;
    const role = document.querySelector('input[name="role"]:checked').value;  // Capture role (admin/user)

    try {
      const userCredential = await createUserWithEmailAndPassword(auth, email, password);
      const user = userCredential.user;

      // Add user to Firestore 'users' collection with role
      await setDoc(doc(db, "users", user.uid), {
        id: user.uid,
        email: user.email,
        role: role,  // Save role
        created_at: new Date().toISOString()
      });

      await setTokenCookie(user);  // Set token cookie
      window.location.href = "/";  // Redirect to home page after registration
    } catch (error) {
      console.error("Signup error:", error.message);
      alert("Signup failed: " + error.message);
    }
  });
}
