import 'package:flutter/material.dart';
import '../services/api_service.dart';

class ForgotPasswordScreen extends StatefulWidget {
  const ForgotPasswordScreen({super.key});

  @override
  State<ForgotPasswordScreen> createState() => _ForgotPasswordScreenState();
}

class _ForgotPasswordScreenState extends State<ForgotPasswordScreen> {
  final _emailController = TextEditingController();
  final _otpController = TextEditingController();
  final _passwordController = TextEditingController();
  final _confirmPasswordController = TextEditingController();
  final _apiService = ApiService();

  int _currentStep = 0; // 0: Email, 1: OTP, 2: New Password
  bool _isLoading = false;
  bool _isPasswordVisible = false;

  void _showError(String message) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(message.replaceAll('Exception: ', '')),
        backgroundColor: Colors.redAccent,
        behavior: SnackBarBehavior.floating,
      ),
    );
  }

  void _showSuccess(String message) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(message),
        backgroundColor: Colors.green.shade800,
        behavior: SnackBarBehavior.floating,
      ),
    );
  }

  Future<void> _requestCode() async {
    final email = _emailController.text.trim();
    if (email.isEmpty) {
      _showError('Please enter your email address');
      return;
    }

    setState(() => _isLoading = true);
    FocusScope.of(context).unfocus();

    try {
      await _apiService.requestPasswordReset(email);
      _showSuccess('Reset code sent to your email');
      setState(() => _currentStep = 1);
    } catch (e) {
      _showError(e.toString());
    } finally {
      setState(() => _isLoading = false);
    }
  }

  Future<void> _verifyOtp() async {
    final otp = _otpController.text.trim();
    if (otp.length != 6) {
      _showError('Please enter the 6-digit code');
      return;
    }

    setState(() => _isLoading = true);
    FocusScope.of(context).unfocus();

    try {
      await _apiService.confirmPasswordReset(_emailController.text.trim(), otp, '');
      _showSuccess('Code verified! Set your new password.');
      setState(() => _currentStep = 2);
    } catch (e) {
      _showError(e.toString());
    } finally {
      setState(() => _isLoading = false);
    }
  }

  Future<void> _resetPassword() async {
    final password = _passwordController.text;
    final confirmPassword = _confirmPasswordController.text;

    if (password.length < 6) {
      _showError('Password must be at least 6 characters');
      return;
    }
    if (password != confirmPassword) {
      _showError('Passwords do not match');
      return;
    }

    setState(() => _isLoading = true);
    FocusScope.of(context).unfocus();

    try {
      await _apiService.confirmPasswordReset(
        _emailController.text.trim(),
        _otpController.text.trim(),
        password,
      );
      _showSuccess('Password reset successfully!');
      Navigator.pop(context);
    } catch (e) {
      _showError(e.toString());
    } finally {
      setState(() => _isLoading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Container(
        height: double.infinity,
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
                  Row(
                    children: [
                      IconButton(
                        icon: const Icon(Icons.arrow_back, color: Colors.white70),
                        onPressed: () => Navigator.pop(context),
                      ),
                    ],
                  ),
                  Icon(
                    _currentStep == 0 
                        ? Icons.mail_outline_rounded 
                        : _currentStep == 1 
                            ? Icons.pin_outlined 
                            : Icons.lock_reset_rounded,
                    size: 80,
                    color: Colors.deepPurpleAccent.shade100,
                  ),
                  const SizedBox(height: 16),
                  Text(
                    _currentStep == 0 
                        ? "Reset Password" 
                        : _currentStep == 1 
                            ? "Verify Code" 
                            : "New Password",
                    style: const TextStyle(
                      fontSize: 28,
                      fontWeight: FontWeight.bold,
                      color: Colors.white,
                      letterSpacing: 1.2,
                    ),
                  ),
                  const SizedBox(height: 8),
                  Text(
                    _currentStep == 0 
                        ? "Enter your email to receive a reset code" 
                        : _currentStep == 1 
                            ? "Enter the 6-digit code sent to your email" 
                            : "Enter and confirm your new password",
                    textAlign: TextAlign.center,
                    style: TextStyle(fontSize: 14, color: Colors.grey.shade400),
                  ),
                  const SizedBox(height: 48),

                  Container(
                    padding: const EdgeInsets.all(24),
                    decoration: BoxDecoration(
                      color: Colors.grey.shade900.withOpacity(0.8),
                      borderRadius: BorderRadius.circular(20),
                      border: Border.all(color: Colors.deepPurple.withOpacity(0.3)),
                      boxShadow: const [
                        BoxShadow(
                          color: Colors.black45,
                          blurRadius: 15,
                          offset: Offset(0, 8),
                        )
                      ],
                    ),
                    child: Column(
                      children: [
                        if (_currentStep == 0) ...[
                          _buildTextField(
                            controller: _emailController,
                            label: "Email Address",
                            icon: Icons.email_outlined,
                            keyboardType: TextInputType.emailAddress,
                          ),
                          const SizedBox(height: 32),
                          _buildSubmitButton("Send Reset Code", _requestCode),
                        ],

                        if (_currentStep == 1) ...[
                          _buildTextField(
                            controller: _otpController,
                            label: "6-Digit Code",
                            icon: Icons.vpn_key_outlined,
                            keyboardType: TextInputType.number,
                            maxLength: 6,
                          ),
                          const SizedBox(height: 32),
                          _buildSubmitButton("Verify Code", _verifyOtp),
                          TextButton(
                            onPressed: () => setState(() => _currentStep = 0),
                            child: Text(
                              "Change Email",
                              style: TextStyle(color: Colors.deepPurpleAccent.shade100),
                            ),
                          ),
                        ],

                        if (_currentStep == 2) ...[
                          _buildTextField(
                            controller: _passwordController,
                            label: "New Password",
                            icon: Icons.lock_outline,
                            isPassword: true,
                          ),
                          const SizedBox(height: 16),
                          _buildTextField(
                            controller: _confirmPasswordController,
                            label: "Confirm Password",
                            icon: Icons.lock_reset,
                            isPassword: true,
                          ),
                          const SizedBox(height: 32),
                          _buildSubmitButton("Update Password", _resetPassword),
                        ],
                      ],
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

  Widget _buildTextField({
    required TextEditingController controller,
    required String label,
    required IconData icon,
    bool isPassword = false,
    TextInputType keyboardType = TextInputType.text,
    int? maxLength,
  }) {
    return TextField(
      controller: controller,
      obscureText: isPassword && !_isPasswordVisible,
      keyboardType: keyboardType,
      maxLength: maxLength,
      style: const TextStyle(color: Colors.white, fontSize: 16),
      decoration: InputDecoration(
        labelText: label,
        labelStyle: TextStyle(color: Colors.grey.shade500),
        prefixIcon: Icon(icon, color: Colors.deepPurpleAccent.shade100, size: 22),
        suffixIcon: isPassword
            ? IconButton(
                icon: Icon(
                  _isPasswordVisible ? Icons.visibility : Icons.visibility_off,
                  color: Colors.grey.shade600,
                  size: 20,
                ),
                onPressed: () => setState(() => _isPasswordVisible = !_isPasswordVisible),
              )
            : null,
        counterText: "",
        enabledBorder: UnderlineInputBorder(
          borderSide: BorderSide(color: Colors.grey.shade800),
        ),
        focusedBorder: const UnderlineInputBorder(
          borderSide: BorderSide(color: Colors.deepPurpleAccent, width: 2),
        ),
      ),
    );
  }

  Widget _buildSubmitButton(String text, VoidCallback onPressed) {
    return Container(
      width: double.infinity,
      height: 55,
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(15),
        gradient: LinearGradient(
          colors: [Colors.deepPurpleAccent, Colors.deepPurple.shade700],
        ),
        boxShadow: [
          BoxShadow(
            color: Colors.deepPurpleAccent.withOpacity(0.3),
            blurRadius: 10,
            offset: const Offset(0, 4),
          )
        ],
      ),
      child: ElevatedButton(
        onPressed: _isLoading ? null : onPressed,
        style: ElevatedButton.styleFrom(
          backgroundColor: Colors.transparent,
          shadowColor: Colors.transparent,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(15)),
        ),
        child: _isLoading
            ? const SizedBox(
                height: 24,
                width: 24,
                child: CircularProgressIndicator(color: Colors.white, strokeWidth: 2),
              )
            : Text(
                text,
                style: const TextStyle(
                  fontSize: 16,
                  fontWeight: FontWeight.bold,
                  color: Colors.white,
                  letterSpacing: 1,
                ),
              ),
      ),
    );
  }
}
