import 'package:flutter/material.dart';
import '../services/api_service.dart';

class ForgotPasswordScreen extends StatefulWidget {
  @override
  _ForgotPasswordScreenState createState() => _ForgotPasswordScreenState();
}

class _ForgotPasswordScreenState extends State<ForgotPasswordScreen> {
  final ApiService api = ApiService();
  final TextEditingController _emailController = TextEditingController();
  final TextEditingController _otpController = TextEditingController();
  final TextEditingController _passwordController = TextEditingController();
  
  bool _otpSent = false;
  bool _isLoading = false;

  Future<void> _requestReset() async {
    if (_emailController.text.isEmpty) return;
    
    // Dismiss keyboard to prevent animation jank
    FocusScope.of(context).unfocus();
    
    setState(() => _isLoading = true);
    try {
      await api.requestPasswordReset(_emailController.text.trim());
      setState(() => _otpSent = true);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('OTP sent to your email!')),
      );
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Error: $e'), backgroundColor: Colors.redAccent),
      );
    } finally {
      setState(() => _isLoading = false);
    }
  }

  Future<void> _confirmReset() async {
    if (_otpController.text.isEmpty || _passwordController.text.isEmpty) return;
    
    // Dismiss keyboard
    FocusScope.of(context).unfocus();
    
    setState(() => _isLoading = true);
    try {
      await api.confirmPasswordReset(
        _emailController.text.trim(),
        _otpController.text.trim(),
        _passwordController.text,
      );
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Password reset successfully!')),
      );
      Navigator.pop(context);
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Error: $e'), backgroundColor: Colors.redAccent),
      );
    } finally {
      setState(() => _isLoading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Color(0xFF0F0F1E),
      appBar: AppBar(
        title: Text('Reset Password'),
        backgroundColor: Colors.transparent,
        elevation: 0,
      ),
      body: Center(
        child: SingleChildScrollView(
          padding: EdgeInsets.all(24),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(
                _otpSent ? Icons.mark_email_read_outlined : Icons.lock_reset_rounded,
                size: 80,
                color: Colors.deepPurpleAccent,
              ),
              SizedBox(height: 24),
              Text(
                _otpSent ? 'Enter OTP' : 'Forgot Password?',
                style: TextStyle(fontSize: 24, fontWeight: FontWeight.bold),
              ),
              SizedBox(height: 8),
              Text(
                _otpSent 
                  ? 'We have sent a 6-digit code to ${_emailController.text}'
                  : 'Enter your email to receive a password reset code',
                textAlign: TextAlign.center,
                style: TextStyle(color: Colors.grey),
              ),
              SizedBox(height: 32),
              
              if (!_otpSent) ...[
                _buildTextField(
                  controller: _emailController,
                  label: 'Email Address',
                  icon: Icons.email_outlined,
                  keyboardType: TextInputType.emailAddress,
                ),
                SizedBox(height: 24),
                _buildButton(
                  text: 'Send Reset Code',
                  onPressed: _requestReset,
                ),
              ] else ...[
                _buildTextField(
                  controller: _otpController,
                  label: '6-Digit OTP',
                  icon: Icons.pin_outlined,
                  keyboardType: TextInputType.number,
                ),
                SizedBox(height: 16),
                _buildTextField(
                  controller: _passwordController,
                  label: 'New Password',
                  icon: Icons.password_rounded,
                  isPassword: true,
                ),
                SizedBox(height: 24),
                _buildButton(
                  text: 'Reset Password',
                  onPressed: _confirmReset,
                ),
                TextButton(
                  onPressed: () => setState(() => _otpSent = false),
                  child: Text('Change Email', style: TextStyle(color: Colors.grey)),
                ),
              ],
            ],
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
    TextInputType? keyboardType,
  }) {
    return TextField(
      controller: controller,
      obscureText: isPassword,
      keyboardType: keyboardType,
      style: TextStyle(color: Colors.white),
      decoration: InputDecoration(
        labelText: label,
        labelStyle: TextStyle(color: Colors.grey),
        prefixIcon: Icon(icon, color: Colors.deepPurpleAccent),
        filled: true,
        fillColor: Color(0xFF1A1A2E),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: BorderSide.none,
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: BorderSide(color: Colors.white.withOpacity(0.1)),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: BorderSide(color: Colors.deepPurpleAccent),
        ),
      ),
    );
  }

  Widget _buildButton({required String text, required VoidCallback onPressed}) {
    return SizedBox(
      width: double.infinity,
      height: 55,
      child: ElevatedButton(
        style: ElevatedButton.styleFrom(
          backgroundColor: Colors.deepPurpleAccent,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
          elevation: 0,
        ),
        onPressed: _isLoading ? null : onPressed,
        child: _isLoading
          ? CircularProgressIndicator(color: Colors.white)
          : Text(
              text,
              style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold, color: Colors.white),
            ),
      ),
    );
  }
}
