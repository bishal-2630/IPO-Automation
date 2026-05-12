import 'package:flutter/material.dart';
import '../services/api_service.dart';
import 'home.dart';
import 'register_screen.dart';
import 'forgot_password_screen.dart';

class LoginScreen extends StatefulWidget {
  @override
  _LoginScreenState createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _usernameController = TextEditingController();
  final _passwordController = TextEditingController();
  final ApiService api = ApiService();
  bool isLoading = false;
  bool _isPasswordVisible = false;

  void submit() async {
    if (_usernameController.text.trim().isEmpty || _passwordController.text.trim().isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text("Please enter both username and password.")),
      );
      return;
    }

    setState(() => isLoading = true);
    try {
      bool success = await api.login(_usernameController.text.trim(), _passwordController.text.trim());
      if (success) {
        Navigator.pushReplacement(context, MaterialPageRoute(builder: (context) => HomeScreen()));
      } else {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text("Login failed. Please check your credentials."),
            backgroundColor: Colors.redAccent,
          ),
        );
      }
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text("Network or Server Error: $e"),
          backgroundColor: Colors.redAccent,
        ),
      );
    } finally {
      setState(() => isLoading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Container(
        decoration: BoxDecoration(
          gradient: LinearGradient(
            colors: [Colors.deepPurple.shade900, Colors.black87],
            begin: Alignment.topCenter,
            end: Alignment.bottomCenter,
          ),
        ),
        child: SafeArea(
          child: Center(
            child: SingleChildScrollView(
              padding: const EdgeInsets.symmetric(horizontal: 24.0),
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Icon(
                    Icons.lock_outline_rounded,
                    size: 80,
                    color: Colors.deepPurpleAccent.shade100,
                  ),
                  SizedBox(height: 16),
                  Text(
                    "Welcome Back",
                    style: TextStyle(
                      fontSize: 28,
                      fontWeight: FontWeight.bold,
                      color: Colors.white,
                      letterSpacing: 1.2,
                    ),
                  ),
                  SizedBox(height: 8),
                  Text(
                    "Sign in to manage your IPOs",
                    style: TextStyle(fontSize: 14, color: Colors.grey.shade400),
                  ),
                  SizedBox(height: 48),

                  Container(
                    padding: EdgeInsets.all(24),
                    decoration: BoxDecoration(
                      color: Colors.grey.shade900.withOpacity(0.8),
                      borderRadius: BorderRadius.circular(20),
                      border: Border.all(color: Colors.deepPurple.withOpacity(0.3)),
                      boxShadow: [
                        BoxShadow(
                          color: Colors.black45,
                          blurRadius: 15,
                          offset: Offset(0, 10),
                        ),
                      ],
                    ),
                    child: Column(
                      children: [
                        TextField(
                          controller: _usernameController,
                          style: TextStyle(color: Colors.white),
                          decoration: InputDecoration(
                            labelText: "Username",
                            labelStyle: TextStyle(color: Colors.grey.shade500),
                            prefixIcon: Icon(Icons.person_outline, color: Colors.deepPurpleAccent.shade100),
                            enabledBorder: OutlineInputBorder(
                              borderRadius: BorderRadius.circular(12),
                              borderSide: BorderSide(color: Colors.grey.shade800),
                            ),
                            focusedBorder: OutlineInputBorder(
                              borderRadius: BorderRadius.circular(12),
                              borderSide: BorderSide(color: Colors.deepPurpleAccent),
                            ),
                            filled: true,
                            fillColor: Colors.black38,
                          ),
                        ),
                        SizedBox(height: 20),
                        TextField(
                          controller: _passwordController,
                          obscureText: !_isPasswordVisible,
                          style: TextStyle(color: Colors.white),
                          decoration: InputDecoration(
                            labelText: "Password",
                            labelStyle: TextStyle(color: Colors.grey.shade500),
                            prefixIcon: Icon(Icons.shield_outlined, color: Colors.deepPurpleAccent.shade100),
                            suffixIcon: IconButton(
                              icon: Icon(
                                _isPasswordVisible ? Icons.visibility : Icons.visibility_off,
                                color: Colors.grey.shade500,
                              ),
                              onPressed: () {
                                setState(() {
                                  _isPasswordVisible = !_isPasswordVisible;
                                });
                              },
                            ),
                            enabledBorder: OutlineInputBorder(
                              borderRadius: BorderRadius.circular(12),
                              borderSide: BorderSide(color: Colors.grey.shade800),
                            ),
                            focusedBorder: OutlineInputBorder(
                              borderRadius: BorderRadius.circular(12),
                              borderSide: BorderSide(color: Colors.deepPurpleAccent),
                            ),
                            filled: true,
                            fillColor: Colors.black38,
                          ),
                        ),
                        Align(
                          alignment: Alignment.centerRight,
                          child: TextButton(
                            onPressed: () {
                              Navigator.push(context, MaterialPageRoute(builder: (context) => ForgotPasswordScreen()));
                            },
                            child: Text(
                              "Forgot Password?",
                              style: TextStyle(color: Colors.grey.shade400, fontSize: 13),
                            ),
                          ),
                        ),
                        SizedBox(height: 16),
                        SizedBox(
                          width: double.infinity,
                          height: 50,
                          child: ElevatedButton(
                            onPressed: isLoading ? null : submit,
                            style: ElevatedButton.styleFrom(
                              backgroundColor: Colors.deepPurpleAccent,
                              shape: RoundedRectangleBorder(
                                borderRadius: BorderRadius.circular(12),
                              ),
                              elevation: 5,
                            ),
                            child: isLoading
                                ? SizedBox(
                                    height: 24,
                                    width: 24,
                                    child: CircularProgressIndicator(color: Colors.white, strokeWidth: 2),
                                  )
                                : Text(
                                    "LOGIN",
                                    style: TextStyle(
                                      fontSize: 16,
                                      fontWeight: FontWeight.bold,
                                      letterSpacing: 1.5,
                                    ),
                                  ),
                          ),
                        ),
                      ],
                    ),
                  ),

                  SizedBox(height: 24),
                  TextButton(
                    onPressed: () {
                      Navigator.push(context, MaterialPageRoute(builder: (context) => RegisterScreen()));
                    },
                    style: TextButton.styleFrom(
                      foregroundColor: Colors.deepPurpleAccent.shade100,
                    ),
                    child: RichText(
                      text: TextSpan(
                        text: "Don't have an account? ",
                        style: TextStyle(color: Colors.grey.shade400, fontSize: 14),
                        children: [
                          TextSpan(
                            text: "Create one",
                            style: TextStyle(
                              color: Colors.deepPurpleAccent.shade100,
                              fontWeight: FontWeight.bold,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
